import dataclasses
import datetime
import json
from typing import Dict
from django.conf import settings
from django.db import DatabaseError
from rest_framework.exceptions import ValidationError
from asgiref.sync import sync_to_async, async_to_sync
from temporalio.client import Client

import structlog
from posthog.models.feature_flag.flag_matching import (
    FeatureFlagMatcher,
    FlagsMatcherCache,
    get_feature_flag_hash_key_overrides,
)
from posthog.models.filters.filter import Filter
from posthog.models.person.person import PersonDistinctId
from posthog.models.property.property import Property, PropertyGroup
from posthog.queries.base import property_group_to_Q
from django.db.models import Prefetch, prefetch_related_objects, OuterRef, Subquery
from posthog.constants import PropertyOperatorType
from sentry_sdk import capture_exception
from posthog.models import Cohort, FeatureFlag, Person
from temporalio import activity, workflow

from posthog.temporal.workflows.base import PostHogWorkflow

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class CreateCohortForFlagWorkflowInputs:
    """Inputs to the cohort_for_flag activity.

    Attributes:
        team_id: The id of the team
        cohort_id: The id of the cohort to populate.
        flag: The feature flag to use for matching persons.
        batchsize: The number of persons to process at a time.
    """

    team_id: int
    cohort_id: int
    flag: str
    batchsize: int


@async_to_sync
async def start_cohort_from_flag_workflow(temporal: Client, inputs: CreateCohortForFlagWorkflowInputs) -> str:
    workflow_id = f"{inputs.team_id}-cohort-{inputs.cohort_id}-for-flag-{inputs.flag}"
    await temporal.start_workflow(
        "cohort_for_flag",
        inputs,
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
    )

    return workflow_id


@workflow.defn(name="cohort_for_flag")
class CreateCohortForFlagWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CreateCohortForFlagWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return CreateCohortForFlagWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: CreateCohortForFlagWorkflowInputs):
        """Workflow implementation to create cohort from feature flag."""
        cohort_for_flag_inputs = CohortForFlagInputs(
            team_id=inputs.team_id,
            cohort_id=inputs.cohort_id,
            flag=inputs.flag,
            batchsize=inputs.batchsize,
        )

        await workflow.execute_activity(
            cohort_for_flag,
            cohort_for_flag_inputs,
            schedule_to_close_timeout=datetime.timedelta(hours=24),
        )


@dataclasses.dataclass
class CohortForFlagInputs:
    """Inputs to the cohort_for_flag activity.

    Attributes:
        team_id: The id of the team
        cohort_id: The id of the cohort to populate.
        flag: The feature flag to use for matching persons.
        batchsize: The number of persons to process at a time.
    """

    team_id: int
    cohort_id: int
    flag: str
    batchsize: int


# TODO: Maybe it's better for the activity to be for a specific batch?
# So if we need to retry, due to say network partitions, it's only that specific batch that is retried, and not the whole thing.
# and then we can have much smaller timeouts per batch
# TODO: Does logging & sentry capture exception work as usual?
@activity.defn
async def cohort_for_flag(inputs: CohortForFlagInputs) -> None:
    """Populate a cohort with persons that match a feature flag.

    Args:
        inputs: The inputs to the activity.
    """

    await sync_to_async(get_cohort_actors_for_feature_flag)(  # type: ignore
        cohort_id=inputs.cohort_id,
        flag=inputs.flag,
        team_id=inputs.team_id,
        batchsize=inputs.batchsize,
    )


def get_cohort_actors_for_feature_flag(cohort_id: int, flag: str, team_id: int, batchsize: int = 1_000):
    # :TODO: Find a way to incorporate this into the same code path as feature flag evaluation
    try:
        feature_flag = FeatureFlag.objects.get(team_id=team_id, key=flag)
    except FeatureFlag.DoesNotExist:
        return []

    if not feature_flag.active or feature_flag.deleted or feature_flag.aggregation_group_type_index is not None:
        return []

    cohort = Cohort.objects.get(pk=cohort_id)
    matcher_cache = FlagsMatcherCache(team_id)
    uuids_to_add_to_cohort = []
    cohorts_cache = {}

    if feature_flag.uses_cohorts:
        # TODO: Consider disabling flags with cohorts for creating static cohorts
        # because this is currently a lot more inefficient for flag matching,
        # as we're required to go to the database for each person.
        cohorts_cache = {cohort.pk: cohort for cohort in Cohort.objects.filter(team_id=team_id, deleted=False)}

    default_person_properties = {}
    for condition in feature_flag.conditions:
        property_list = Filter(data=condition).property_groups.flat
        for property in property_list:
            default_person_properties.update(get_default_person_property(property, cohorts_cache))

    flag_property_conditions = [Filter(data=condition).property_groups for condition in feature_flag.conditions]
    flag_property_group = PropertyGroup(type=PropertyOperatorType.OR, values=flag_property_conditions)

    try:
        # QuerySet.Iterator() doesn't work with pgbouncer, it will load everything into memory and then stream
        # which doesn't work for us, so need a manual chunking here.
        # Because of this pgbouncer transaction pooling mode, we can't use server-side cursors.
        # We pre-filter all persons to be ones that will match the feature flag, so that we don't have to
        # iterate through all persons
        queryset = (
            Person.objects.filter(team_id=team_id)
            .filter(property_group_to_Q(flag_property_group, cohorts_cache=cohorts_cache))
            .order_by("id")
        )
        # get batchsize number of people at a time
        start = 0
        batch_of_persons = queryset[start : start + batchsize]
        while batch_of_persons:
            # TODO: Check if this subquery bulk fetch limiting is better than just doing a join for all distinct ids
            # OR, if row by row getting single distinct id is better
            # distinct_id = PersonDistinctId.objects.filter(person=person, team_id=team_id).values_list(
            #     "distinct_id", flat=True
            # )[0]
            distinct_id_subquery = Subquery(
                PersonDistinctId.objects.filter(person_id=OuterRef("person_id")).values_list("id", flat=True)[:3]
            )
            prefetch_related_objects(
                batch_of_persons,
                Prefetch(
                    "persondistinctid_set",
                    to_attr="distinct_ids_cache",
                    queryset=PersonDistinctId.objects.filter(id__in=distinct_id_subquery),
                ),
            )

            all_persons = list(batch_of_persons)
            if len(all_persons) == 0:
                break

            for person in all_persons:
                # ignore almost-deleted persons / persons with no distinct ids
                if len(person.distinct_ids) == 0:
                    continue

                distinct_id = person.distinct_ids[0]
                person_overrides = {}
                if feature_flag.ensure_experience_continuity:
                    # :TRICKY: This is inefficient because it tries to get the hashkey overrides one by one.
                    # But reusing functions is better for maintainability. Revisit optimising if this becomes a bottleneck.
                    person_overrides = get_feature_flag_hash_key_overrides(
                        team_id, [distinct_id], person_id_to_distinct_id_mapping={person.id: distinct_id}
                    )

                try:
                    match = FeatureFlagMatcher(
                        [feature_flag],
                        distinct_id,
                        groups={},
                        cache=matcher_cache,
                        hash_key_overrides=person_overrides,
                        property_value_overrides={**default_person_properties, **person.properties},
                        group_property_value_overrides={},
                        cohorts_cache=cohorts_cache,
                    ).get_match(feature_flag)
                    if match.match:
                        uuids_to_add_to_cohort.append(str(person.uuid))
                except (DatabaseError, ValueError, ValidationError):
                    logger.exception(
                        "Error evaluating feature flag for person", person_uuid=str(person.uuid), team_id=team_id
                    )
                except Exception as err:
                    # matching errors are not fatal, so we just log them and move on.
                    # Capturing in sentry for now just in case there are some unexpected errors
                    # we did not account for.
                    capture_exception(err)

                if len(uuids_to_add_to_cohort) >= batchsize:
                    cohort.insert_users_list_by_uuid(
                        uuids_to_add_to_cohort, insert_in_clickhouse=True, batchsize=batchsize
                    )
                    uuids_to_add_to_cohort = []

            start += batchsize
            batch_of_persons = queryset[start : start + batchsize]

        if len(uuids_to_add_to_cohort) > 0:
            cohort.insert_users_list_by_uuid(uuids_to_add_to_cohort, insert_in_clickhouse=True, batchsize=batchsize)

    except Exception as err:
        if settings.DEBUG or settings.TEST:
            raise err
        capture_exception(err)


def get_default_person_property(prop: Property, cohorts_cache: Dict[int, Cohort]):
    default_person_properties = {}

    if prop.operator not in ("is_set", "is_not_set") and prop.type == "person":
        default_person_properties[prop.key] = ""
    elif prop.type == "cohort" and not isinstance(prop.value, list):
        try:
            parsed_cohort_id = int(prop.value)
        except (ValueError, TypeError):
            return None
        cohort = cohorts_cache.get(parsed_cohort_id)
        if cohort:
            return get_default_person_properties_for_cohort(cohort, cohorts_cache)
    return default_person_properties


def get_default_person_properties_for_cohort(cohort: Cohort, cohorts_cache: Dict[int, Cohort]) -> Dict[str, str]:
    """
    Returns a dictionary of default person properties to use when evaluating a feature flag
    """
    default_person_properties = {}
    for property in cohort.properties.flat:
        default_person_properties.update(get_default_person_property(property, cohorts_cache))

    return default_person_properties
