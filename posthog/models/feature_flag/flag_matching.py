import time
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Optional, Union, cast

from django.conf import settings
from django.db import DatabaseError, IntegrityError, connections
from django.db.models import CharField, Expression, F, Func, Q
from django.db.models.expressions import ExpressionWrapper, RawSQL
from django.db.models.fields import BooleanField
from django.db.models.query import QuerySet

import structlog
from prometheus_client import Counter

from posthog.constants import SURVEY_TARGETING_FLAG_PREFIX
from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.exceptions_capture import capture_exception
from posthog.helpers.encrypted_flag_payloads import get_decrypted_flag_payload
from posthog.metrics import LABEL_TEAM_ID
from posthog.models.cohort import Cohort, CohortOrEmpty
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person, PersonDistinctId
from posthog.models.property import GroupTypeIndex, GroupTypeName
from posthog.models.property.property import Property
from posthog.models.team.team import Team
from posthog.models.utils import execute_with_timeout
from posthog.queries.base import match_property, properties_to_Q, sanitize_property_key
from posthog.utils import label_for_team_id_to_track

from .feature_flag import (
    FeatureFlag,
    FeatureFlagHashKeyOverride,
    get_feature_flags_for_team_in_cache,
    set_feature_flags_for_team_in_cache,
)

logger = structlog.get_logger(__name__)

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)

FLAG_MATCHING_QUERY_TIMEOUT_MS = 500  # 500 ms. Any longer and we'll just error out.

FLAG_EVALUATION_ERROR_COUNTER = Counter(
    "flag_evaluation_error_total",
    "Failed decide requests with reason.",
    labelnames=["reason"],
)

FLAG_HASH_KEY_WRITES_COUNTER = Counter(
    "flag_hash_key_writes_total",
    "Attempts to write hash key overrides to the database.",
    labelnames=[LABEL_TEAM_ID, "successful_write"],
)


FLAG_CACHE_HIT_COUNTER = Counter(
    "flag_cache_hit_total",
    "Whether we could get all flags from the cache or not.",
    labelnames=[LABEL_TEAM_ID, "cache_hit"],
)

ENTITY_EXISTS_PREFIX = "flag_entity_exists_"
PERSON_KEY = "person"

# Define which database to use for persons only.
# This is temporary while we migrate persons to its own database.
# It'll use `replica` until we set the PERSONS_DB_WRITER_URL env var
READ_ONLY_DATABASE_FOR_PERSONS = (
    "persons_db_reader"
    if "persons_db_reader" in connections
    else "replica"
    if "replica" in connections and "decide" in settings.READ_REPLICA_OPT_IN
    else "default"
)  # Fallback if persons DB not configured

WRITE_DATABASE_FOR_PERSONS = "persons_db_writer" if "persons_db_writer" in connections else "default"


class FeatureFlagMatchReason(StrEnum):
    SUPER_CONDITION_VALUE = "super_condition_value"
    HOLDOUT_CONDITION_VALUE = "holdout_condition_value"
    CONDITION_MATCH = "condition_match"
    NO_CONDITION_MATCH = "no_condition_match"
    OUT_OF_ROLLOUT_BOUND = "out_of_rollout_bound"
    NO_GROUP_TYPE = "no_group_type"

    def score(self) -> float:
        match self:
            case FeatureFlagMatchReason.SUPER_CONDITION_VALUE:
                return 4
            case FeatureFlagMatchReason.HOLDOUT_CONDITION_VALUE:
                return 3.5
            case FeatureFlagMatchReason.CONDITION_MATCH:
                return 3
            case FeatureFlagMatchReason.NO_GROUP_TYPE:
                return 2
            case FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND:
                return 1
            case FeatureFlagMatchReason.NO_CONDITION_MATCH:
                return 0
            case _:
                raise AssertionError("Unreachable - all enum cases are handled")

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.score() < other.score()

        raise NotImplementedError(f"Cannot compare {self.__class__} and {other.__class__}")


@dataclass(frozen=True)
class FeatureFlagMatch:
    match: bool = False
    variant: Optional[str] = None
    reason: FeatureFlagMatchReason = FeatureFlagMatchReason.NO_CONDITION_MATCH
    condition_index: Optional[int] = None
    payload: Optional[object] = None


@dataclass(frozen=True)
class FeatureFlagDetails:
    match: FeatureFlagMatch
    id: int = 0
    version: int = 0
    description: Optional[str] = None


class FlagsMatcherCache:
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.failed_to_fetch_flags = False

    @cached_property
    def group_types_to_indexes(self) -> dict[GroupTypeName, GroupTypeIndex]:
        if self.failed_to_fetch_flags:
            raise DatabaseError("Failed to fetch group type mapping previously, not trying again.")
        try:
            with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS, DATABASE_FOR_FLAG_MATCHING):
                group_type_mapping_rows = GroupTypeMapping.objects.db_manager(DATABASE_FOR_FLAG_MATCHING).filter(
                    project_id=self.project_id
                )
                return {row.group_type: cast(GroupTypeIndex, row.group_type_index) for row in group_type_mapping_rows}
        except DatabaseError as e:
            logger.exception("group_types_to_indexes database error", error=str(e), exc_info=True)
            self.failed_to_fetch_flags = True
            raise

    @cached_property
    def group_type_index_to_name(self) -> dict[GroupTypeIndex, GroupTypeName]:
        return {value: key for key, value in self.group_types_to_indexes.items()}


class FeatureFlagMatcher:
    failed_to_fetch_conditions = False

    def __init__(
        self,
        team_id: int,
        project_id: int,
        feature_flags: list[FeatureFlag],
        distinct_id: str,
        groups: Optional[dict[GroupTypeName, str]] = None,
        cache: Optional[FlagsMatcherCache] = None,
        hash_key_overrides: Optional[dict[str, str]] = None,
        property_value_overrides: Optional[dict[str, Union[str, int]]] = None,
        group_property_value_overrides: Optional[dict[str, dict[str, Union[str, int]]]] = None,
        skip_database_flags: bool = False,
        cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
    ):
        if group_property_value_overrides is None:
            group_property_value_overrides = {}
        if property_value_overrides is None:
            property_value_overrides = {}
        if hash_key_overrides is None:
            hash_key_overrides = {}
        if groups is None:
            groups = {}
        self.team_id = team_id
        self.project_id = project_id
        self.feature_flags = feature_flags
        self.distinct_id = distinct_id
        self.groups = groups
        self.cache = cache or FlagsMatcherCache(project_id)
        self.hash_key_overrides = hash_key_overrides
        self.property_value_overrides = property_value_overrides
        self.group_property_value_overrides = group_property_value_overrides
        self.skip_database_flags = skip_database_flags

        if cohorts_cache is None:
            self.cohorts_cache = {}
        else:
            self.cohorts_cache = cohorts_cache

    def get_match(self, feature_flag: FeatureFlag) -> FeatureFlagMatch:
        # If aggregating flag by groups and relevant group type is not passed - flag is off!
        if self.hashed_identifier(feature_flag) is None:
            return FeatureFlagMatch(match=False, reason=FeatureFlagMatchReason.NO_GROUP_TYPE)

        highest_priority_evaluation_reason = FeatureFlagMatchReason.NO_CONDITION_MATCH
        highest_priority_index = 0

        # Match for boolean super condition first
        if feature_flag.filters.get("super_groups", None):
            (
                is_match,
                super_condition_value,
                evaluation_reason,
            ) = self.is_super_condition_match(feature_flag)
            if is_match:
                payload = self.get_matching_payload(super_condition_value, None, feature_flag)
                return FeatureFlagMatch(
                    match=super_condition_value,
                    reason=evaluation_reason,
                    condition_index=0,
                    payload=payload,
                )

        # Match for holdout super condition
        # TODO: Flags shouldn't have both super_groups and holdout_groups
        # TODO: Validate only multivariant flags to have holdout groups. I could make this implicit by reusing super_groups but
        # this will shoot ourselves in the foot when we extend early access to support variants as well.
        # TODO: Validate holdout variant should have 0% default rollout %?
        # TODO: All this validation we need to do suggests the modelling is imperfect here. Carrying forward for now, we'll only enable
        # in beta, and potentially rework representation before rolling out to everyone. Probably the problem is holdout groups are an
        # experiment level concept that applies across experiments, and we are creating a feature flag level primitive to handle it.
        # Validating things like the variant name is the same across all flags, rolled out to 0%, has the same correct conditions is a bit of
        # a pain here. But I'm not sure if feature flags should indeed know all this info. It's fine for them to just work with what they're given.
        if feature_flag.filters.get("holdout_groups", None):
            (
                is_match,
                holdout_value,
                evaluation_reason,
            ) = self.is_holdout_condition_match(feature_flag)
            if is_match:
                payload = self.get_matching_payload(is_match, holdout_value, feature_flag)
                return FeatureFlagMatch(
                    match=is_match,
                    variant=holdout_value,
                    reason=evaluation_reason,
                    condition_index=0,
                    payload=payload,
                )

        # Stable sort conditions with variant overrides to the top. This ensures that if overrides are present, they are
        # evaluated first, and the variant override is applied to the first matching condition.
        # :TRICKY: We need to include the enumeration index before the sort so the flag evaluation reason gets the right condition index.
        sorted_flag_conditions = sorted(
            enumerate(feature_flag.conditions),
            key=lambda condition_tuple: 0 if condition_tuple[1].get("variant") else 1,
        )
        for index, condition in sorted_flag_conditions:
            is_match, evaluation_reason = self.is_condition_match(feature_flag, condition, index)
            if is_match:
                variant_override = condition.get("variant")
                if variant_override in [variant["key"] for variant in feature_flag.variants]:
                    variant = variant_override
                else:
                    variant = self.get_matching_variant(feature_flag)

                payload = self.get_matching_payload(is_match, variant, feature_flag)
                return FeatureFlagMatch(
                    match=True,
                    variant=variant,
                    reason=evaluation_reason,
                    condition_index=index,
                    payload=payload,
                )

            (
                highest_priority_evaluation_reason,
                highest_priority_index,
            ) = self.get_highest_priority_match_evaluation(
                highest_priority_evaluation_reason,
                highest_priority_index,
                evaluation_reason,
                index,
            )

        return FeatureFlagMatch(
            match=False,
            reason=highest_priority_evaluation_reason,
            condition_index=highest_priority_index,
            payload=None,
        )

    def get_matches_with_details(
        self,
    ) -> tuple[
        dict[str, Union[str, bool]], dict[str, dict], dict[str, object], bool, Optional[dict[str, FeatureFlagDetails]]
    ]:
        flags_details = {}
        flag_values = {}
        flag_evaluation_reasons = {}
        faced_error_computing_flags = False
        flag_payloads = {}
        for feature_flag in self.feature_flags:
            if self.skip_database_flags:
                # both group based and experience continuity based flags need a database connection
                if feature_flag.ensure_experience_continuity or feature_flag.aggregation_group_type_index is not None:
                    faced_error_computing_flags = True
                    continue
            try:
                flag_match = self.get_match(feature_flag)

                flags_details[feature_flag.key] = FeatureFlagDetails(
                    match=flag_match,
                    id=feature_flag.id,
                    version=feature_flag.version or 1,
                    description=feature_flag.name,
                )

                if flag_match.match:
                    flag_values[feature_flag.key] = flag_match.variant or True
                else:
                    flag_values[feature_flag.key] = False

                if flag_match.payload:
                    flag_payloads[feature_flag.key] = flag_match.payload

                flag_evaluation_reasons[feature_flag.key] = {
                    "reason": flag_match.reason,
                    "condition_index": flag_match.condition_index,
                }
            except Exception as err:
                faced_error_computing_flags = True
                handle_feature_flag_exception(err, "[Feature Flags] Error computing flags")

        return (
            flag_values,
            flag_evaluation_reasons,
            flag_payloads,
            faced_error_computing_flags,
            flags_details,
        )

    def get_matching_variant(self, feature_flag: FeatureFlag) -> Optional[str]:
        # Calculate hash once outside the loop since it's the same for all variants
        variant_hash = self.get_hash(feature_flag, salt="variant")
        for variant in self.variant_lookup_table(feature_flag):
            if variant_hash >= variant["value_min"] and variant_hash < variant["value_max"]:
                return variant["key"]
        return None

    def get_matching_payload(
        self, is_match: bool, match_variant: Optional[str], feature_flag: FeatureFlag
    ) -> Optional[object]:
        if is_match:
            if match_variant:
                return feature_flag.get_payload(match_variant)
            else:
                return (
                    feature_flag.get_payload("true")
                    if not feature_flag.has_encrypted_payloads
                    else get_decrypted_flag_payload(feature_flag.get_payload("true"), should_decrypt=False)
                )
        else:
            return None

    def is_holdout_condition_match(self, feature_flag: FeatureFlag) -> tuple[bool, str | None, FeatureFlagMatchReason]:
        # TODO: Right now holdout conditions only support basic rollout %s, and not property overrides.

        # Evaluate if properties are empty
        if feature_flag.holdout_conditions and len(feature_flag.holdout_conditions) > 0:
            condition = feature_flag.holdout_conditions[0]

            # TODO: Check properties and match based on them

            if not condition.get("properties"):
                rollout_percentage = condition.get("rollout_percentage")

                if rollout_percentage is not None and self.get_holdout_hash(feature_flag) > (rollout_percentage / 100):
                    return False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND

                # rollout_percentage is None (=100%), or we are inside holdout rollout bound.
                # Thus, we match. Now get the variant override for the holdout condition.
                variant_override = condition.get("variant")
                if variant_override:
                    variant = variant_override
                else:
                    variant = self.get_matching_variant(feature_flag)

                return (True, variant, FeatureFlagMatchReason.HOLDOUT_CONDITION_VALUE)

        return False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH

    def is_super_condition_match(self, feature_flag: FeatureFlag) -> tuple[bool, bool, FeatureFlagMatchReason]:
        # TODO: Right now super conditions with property overrides bork when the database is down,
        # because we're still going to the database in the line below. Ideally, we should not go to the database.
        # Don't skip test: test_super_condition_with_override_properties_doesnt_make_database_requests when this is fixed.
        # This also doesn't handle the case when the super condition has a property & a non-100 percentage rollout; but
        # we don't support that with super conditions anyway.
        super_condition_value_is_set = self._super_condition_is_set(feature_flag)
        super_condition_value = self._super_condition_matches(feature_flag)

        if super_condition_value_is_set:
            return (
                True,
                super_condition_value,
                FeatureFlagMatchReason.SUPER_CONDITION_VALUE,
            )

        # Evaluate if properties are empty
        if feature_flag.super_conditions and len(feature_flag.super_conditions) > 0:
            condition = feature_flag.super_conditions[0]

            if not condition.get("properties"):
                is_match, evaluation_reason = self.is_condition_match(feature_flag, condition, 0)
                return (
                    True,
                    is_match,
                    (
                        FeatureFlagMatchReason.SUPER_CONDITION_VALUE
                        if evaluation_reason == FeatureFlagMatchReason.CONDITION_MATCH
                        else evaluation_reason
                    ),
                )

        return False, False, FeatureFlagMatchReason.NO_CONDITION_MATCH

    def is_condition_match(
        self, feature_flag: FeatureFlag, condition: dict, condition_index: int
    ) -> tuple[bool, FeatureFlagMatchReason]:
        rollout_percentage = condition.get("rollout_percentage")
        properties = condition.get("properties")
        if properties and len(properties) > 0:
            properties = Filter(data=condition).property_groups.flat
            if self.can_compute_locally(properties, feature_flag.aggregation_group_type_index):
                # :TRICKY: If overrides are enough to determine if a condition is a match,
                # we can skip checking the query.
                # This ensures match even if the person hasn't been ingested yet.
                target_properties = self.property_value_overrides
                if feature_flag.aggregation_group_type_index is not None:
                    target_properties = self.group_property_value_overrides.get(
                        self.cache.group_type_index_to_name[feature_flag.aggregation_group_type_index],
                        {},
                    )
                condition_match = all(match_property(property, target_properties) for property in properties)
            else:
                match_if_entity_doesnt_exist = check_pure_is_not_operator_condition(condition)
                condition_match = self._condition_matches(
                    feature_flag,
                    condition_index,
                    match_if_entity_doesnt_exist,
                    feature_flag.aggregation_group_type_index,
                )

            if not condition_match:
                return False, FeatureFlagMatchReason.NO_CONDITION_MATCH
            elif rollout_percentage is None:
                return True, FeatureFlagMatchReason.CONDITION_MATCH

        if rollout_percentage is not None and self.get_hash(feature_flag) > (rollout_percentage / 100):
            return False, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND

        return True, FeatureFlagMatchReason.CONDITION_MATCH

    def _super_condition_matches(self, feature_flag: FeatureFlag) -> bool:
        return self._get_query_condition(f"flag_{feature_flag.pk}_super_condition")

    def _super_condition_is_set(self, feature_flag: FeatureFlag) -> Optional[bool]:
        return self._get_query_condition(f"flag_{feature_flag.pk}_super_condition_is_set")

    def _condition_matches(
        self,
        feature_flag: FeatureFlag,
        condition_index: int,
        match_if_entity_doesnt_exist: bool = False,
        group_type_index: Optional[GroupTypeIndex] = None,
    ) -> bool:
        return self._get_query_condition(
            f"flag_{feature_flag.pk}_condition_{condition_index}", match_if_entity_doesnt_exist, group_type_index
        )

    def _get_query_condition(
        self, key: str, match_if_entity_doesnt_exist: bool = False, group_type_index: Optional[GroupTypeIndex] = None
    ) -> bool:
        if self.failed_to_fetch_conditions:
            raise DatabaseError("Failed to fetch conditions for feature flag previously, not trying again.")
        if self.skip_database_flags:
            raise DatabaseError("Database healthcheck failed, not fetching flag conditions.")

        # :TRICKY: Currently this option is only set with the is_not_set operator, but we can shortcircuit the condition check
        # if the person doesn't exist. This is important as it allows resolving flags correctly for non-ingested persons.
        if match_if_entity_doesnt_exist:
            existence_key = f"{ENTITY_EXISTS_PREFIX}{group_type_index if group_type_index is not None else PERSON_KEY}"
            entity_doesnt_exist = self.query_conditions.get(existence_key) is False
            # :TRICKY: We only return if entity doesn't exist, because if it does, we still need to check the condition properly.
            if entity_doesnt_exist:
                return True

        return self.query_conditions.get(key, False)

    # Define contiguous sub-domains within [0, 1].
    # By looking up a random hash value, you can find the associated variant key.
    # e.g. the first of two variants with 50% rollout percentage will have value_max: 0.5
    # and the second will have value_min: 0.5 and value_max: 1.0
    def variant_lookup_table(self, feature_flag: FeatureFlag):
        lookup_table = []
        value_min = 0
        for variant in feature_flag.variants:
            value_max = value_min + variant["rollout_percentage"] / 100
            lookup_table.append({"value_min": value_min, "value_max": value_max, "key": variant["key"]})
            value_min = value_max
        return lookup_table

    @cached_property
    def query_conditions(self) -> dict[str, bool]:
        try:
            with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS * 2, READ_ONLY_DATABASE_FOR_PERSONS):
                # Some extra wiggle room here for timeouts because this depends on the number of flags as well,
                # and not just the database query.
                all_conditions: dict = {}
                person_query: QuerySet = Person.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(
                    team_id=self.team_id,
                    persondistinctid__distinct_id=self.distinct_id,
                    persondistinctid__team_id=self.team_id,
                )
                basic_group_query: QuerySet = Group.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(
                    team_id=self.team_id
                )
                group_query_per_group_type_mapping: dict[GroupTypeIndex, tuple[QuerySet, list[str]]] = {}
                # :TRICKY: Create a queryset for each group type that uniquely identifies a group, based on the groups passed in.
                # If no groups for a group type are passed in, we can skip querying for that group type,
                # since the result will always be `false`.
                for group_type, group_key in self.groups.items():
                    group_type_index = self.cache.group_types_to_indexes.get(group_type)
                    if group_type_index is not None:
                        # a tuple of querySet and field names
                        group_query_per_group_type_mapping[group_type_index] = (
                            basic_group_query.filter(group_type_index=group_type_index, group_key=group_key),
                            [],
                        )

                person_fields: list[str] = []

                for existence_condition_key in self.has_pure_is_not_conditions:
                    if existence_condition_key == PERSON_KEY:
                        person_exists = person_query.exists()
                        all_conditions[f"{ENTITY_EXISTS_PREFIX}{PERSON_KEY}"] = person_exists
                    else:
                        if existence_condition_key not in group_query_per_group_type_mapping:
                            continue

                        group_query, _ = group_query_per_group_type_mapping[
                            cast(GroupTypeIndex, existence_condition_key)
                        ]
                        group_exists = group_query.exists()
                        all_conditions[f"{ENTITY_EXISTS_PREFIX}{existence_condition_key}"] = group_exists

                def condition_eval(key, condition):
                    expr = None
                    annotate_query = True
                    nonlocal person_query

                    property_list = Filter(data=condition).property_groups.flat
                    properties_with_math_operators = get_all_properties_with_math_operators(
                        property_list, self.cohorts_cache, self.project_id
                    )

                    if len(condition.get("properties", {})) > 0:
                        # Feature Flags don't support OR filtering yet
                        target_properties = self.property_value_overrides
                        if feature_flag.aggregation_group_type_index is not None:
                            if feature_flag.aggregation_group_type_index not in self.cache.group_type_index_to_name:
                                target_properties = {}
                            else:
                                target_properties = self.group_property_value_overrides.get(
                                    self.cache.group_type_index_to_name[feature_flag.aggregation_group_type_index],
                                    {},
                                )

                        expr = properties_to_Q(
                            self.project_id,
                            property_list,
                            override_property_values=target_properties,
                            cohorts_cache=self.cohorts_cache,
                            using_database=READ_ONLY_DATABASE_FOR_PERSONS,
                        )

                        # TRICKY: Due to property overrides for cohorts, we sometimes shortcircuit the condition check.
                        # In that case, the expression is either an explicit True or explicit False, or multiple conditions.
                        # We can skip going to the database in explicit True|False conditions. This is important
                        # as it allows resolving flags correctly for non-ingested persons.
                        # However, this doesn't work for the multiple condition case (when expr has multiple Q objects),
                        # but it's better than nothing.
                        # TODO: A proper fix would be to handle cohorts with property overrides before we get to this point.
                        # Unskip test test_complex_cohort_filter_with_override_properties when we fix this.
                        if expr == Q(pk__isnull=False):
                            all_conditions[key] = True
                            annotate_query = False
                        elif expr == Q(pk__isnull=True):
                            all_conditions[key] = False
                            annotate_query = False

                    if annotate_query:
                        if feature_flag.aggregation_group_type_index is None:
                            # :TRICKY: Flag matching depends on type of property when doing >, <, >=, <= comparisons.
                            # This requires a generated field to query in Q objects, which sadly don't allow inlining fields,
                            # hence we need to annotate the query here, even though these annotations are used much deeper,
                            # in properties_to_q, in empty_or_null_with_value_q
                            # These need to come in before the expr so they're available to use inside the expr.
                            # Same holds for the group queries below.
                            type_property_annotations = _get_property_type_annotations(properties_with_math_operators)
                            person_query = person_query.annotate(
                                **type_property_annotations,
                                **{
                                    key: ExpressionWrapper(
                                        cast(Expression, expr if expr else RawSQL("true", [])),
                                        output_field=BooleanField(),
                                    ),
                                },
                            )
                            person_fields.append(key)
                        else:
                            if feature_flag.aggregation_group_type_index not in group_query_per_group_type_mapping:
                                # ignore flags that didn't have the right groups passed in
                                return
                            (
                                group_query,
                                group_fields,
                            ) = group_query_per_group_type_mapping[feature_flag.aggregation_group_type_index]
                            type_property_annotations = _get_property_type_annotations(properties_with_math_operators)
                            group_query = group_query.annotate(
                                **type_property_annotations,
                                **{
                                    key: ExpressionWrapper(
                                        cast(Expression, expr if expr else RawSQL("true", [])),
                                        output_field=BooleanField(),
                                    ),
                                },
                            )
                            group_fields.append(key)
                            group_query_per_group_type_mapping[feature_flag.aggregation_group_type_index] = (
                                group_query,
                                group_fields,
                            )

                # only fetch all cohorts if not passed in any cached cohorts
                if not self.cohorts_cache and any(feature_flag.uses_cohorts for feature_flag in self.feature_flags):
                    with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS * 2, DATABASE_FOR_FLAG_MATCHING):
                        all_cohorts = {
                            cohort.pk: cohort
                            for cohort in Cohort.objects.db_manager(DATABASE_FOR_FLAG_MATCHING).filter(
                                team__project_id=self.project_id, deleted=False
                            )
                        }
                    self.cohorts_cache.update(all_cohorts)
                # release conditions
                for feature_flag in self.feature_flags:
                    # super release conditions
                    if feature_flag.super_conditions and len(feature_flag.super_conditions) > 0:
                        condition = feature_flag.super_conditions[0]
                        prop_key = (condition.get("properties") or [{}])[0].get("key")
                        if prop_key:
                            key = f"flag_{feature_flag.pk}_super_condition"
                            condition_eval(key, condition)

                            is_set_key = f"flag_{feature_flag.pk}_super_condition_is_set"
                            is_set_condition = {
                                "properties": [
                                    {
                                        "key": prop_key,
                                        "operator": "is_set",
                                    }
                                ]
                            }
                            condition_eval(is_set_key, is_set_condition)

                    for index, condition in enumerate(feature_flag.conditions):
                        key = f"flag_{feature_flag.pk}_condition_{index}"
                        condition_eval(key, condition)

                if len(person_fields) > 0:
                    person_query = person_query.values(*person_fields)
                    if len(person_query) > 0:
                        all_conditions = {**all_conditions, **person_query[0]}
                if len(group_query_per_group_type_mapping) > 0:
                    for (
                        group_query,
                        group_fields,
                    ) in group_query_per_group_type_mapping.values():
                        # Only query the group if there's a field to query
                        if len(group_fields) > 0:
                            group_query = group_query.values(*group_fields)
                            if len(group_query) > 0:
                                assert len(group_query) == 1, f"Expected 1 group query result, got {len(group_query)}"
                                all_conditions = {**all_conditions, **group_query[0]}
                return all_conditions
        except DatabaseError as e:
            logger.exception("query_conditions database error", error=str(e), exc_info=True)
            self.failed_to_fetch_conditions = True
            raise
        except Exception:
            # Usually when a user somehow manages to create an invalid filter, usually via API.
            # In this case, don't put db down, just skip the flag.
            # Covers all cases like invalid JSON, invalid operator, invalid property name, invalid group input format, etc.
            raise

    def hashed_identifier(self, feature_flag: FeatureFlag) -> Optional[str]:
        """
        If aggregating by people, returns distinct_id.

        Otherwise, returns the relevant group_key.

        If relevant group is not passed to the flag, None is returned and handled in get_match.
        """
        if feature_flag.aggregation_group_type_index is None:
            if feature_flag.ensure_experience_continuity:
                # TODO: Try a global cache
                if feature_flag.key in self.hash_key_overrides:
                    return self.hash_key_overrides[feature_flag.key]
            return self.distinct_id
        else:
            # TODO: Don't use the cache if self.groups is empty, since that means no groups provided anyway
            # :TRICKY: If aggregating by groups
            group_type_name = self.cache.group_type_index_to_name.get(feature_flag.aggregation_group_type_index)
            if group_type_name is None:
                return None
            group_key = self.groups.get(group_type_name)
            return group_key

    # This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    # Given the same identifier and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    # we can do _hash(key, identifier) < 0.2
    def get_hash(self, feature_flag: FeatureFlag, salt="") -> float:
        return self.calculate_hash(f"{feature_flag.key}.", self.hashed_identifier(feature_flag), salt)

    # This function takes a identifier and a feature flag and returns a float between 0 and 1.
    # Given the same identifier and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, and are keyed only on user's distinct id / group key.
    # Thus, irrespective of the flag, the same user will always get the same value.
    def get_holdout_hash(self, feature_flag: FeatureFlag, salt="") -> float:
        return self.calculate_hash("holdout-", self.hashed_identifier(feature_flag), salt)

    @classmethod
    def calculate_hash(cls, prefix: str, hash_identifier: str | None, salt="") -> float:
        if hash_identifier is None:
            # Return a hash value that will make the flag evaluate to false; since we
            # can't evaluate a flag without an identifier.
            # NB: A flag with 0.0 hash will always evaluate to false
            return 0
        hash_key = f"{prefix}{hash_identifier}{salt}"
        hash_val = int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16)
        return hash_val / __LONG_SCALE__

    def can_compute_locally(
        self,
        properties: list[Property],
        group_type_index: Optional[GroupTypeIndex] = None,
    ) -> bool:
        target_properties = self.property_value_overrides
        if group_type_index is not None:
            target_properties = self.group_property_value_overrides.get(
                self.cache.group_type_index_to_name[group_type_index], {}
            )
        for property in properties:
            # can't locally compute if property is a cohort
            # need to atleast fetch the cohort
            if property.type == "cohort":
                return False
            if property.key not in target_properties:
                return False
        return True

    def get_highest_priority_match_evaluation(
        self,
        current_match: FeatureFlagMatchReason,
        current_index: int,
        new_match: FeatureFlagMatchReason,
        new_index: int,
    ):
        if current_match <= new_match:
            return new_match, new_index

        return current_match, current_index

    @cached_property
    def has_pure_is_not_conditions(self) -> set[Literal["person"] | GroupTypeIndex]:
        entity_to_condition_check: set[Literal["person"] | GroupTypeIndex] = set()
        for feature_flag in self.feature_flags:
            for condition in feature_flag.conditions:
                if check_pure_is_not_operator_condition(condition):
                    if feature_flag.aggregation_group_type_index is not None:
                        entity_to_condition_check.add(feature_flag.aggregation_group_type_index)
                    else:
                        entity_to_condition_check.add("person")

        return entity_to_condition_check


def get_feature_flag_hash_key_overrides(
    team_id: int,
    distinct_ids: list[str],
    using_database: str = WRITE_DATABASE_FOR_PERSONS,
    person_id_to_distinct_id_mapping: Optional[dict[int, str]] = None,
) -> dict[str, str]:
    feature_flag_to_key_overrides = {}

    # Priority to the first distinctID's values, to keep this function deterministic

    if not person_id_to_distinct_id_mapping:
        person_and_distinct_ids = list(
            PersonDistinctId.objects.db_manager(using_database)
            .filter(distinct_id__in=distinct_ids, team_id=team_id)
            .values_list("person_id", "distinct_id")
        )
        person_id_to_distinct_id = dict(person_and_distinct_ids)
    else:
        person_id_to_distinct_id = person_id_to_distinct_id_mapping

    person_ids = list(person_id_to_distinct_id.keys())

    for feature_flag, override, _ in sorted(
        FeatureFlagHashKeyOverride.objects.db_manager(using_database)
        .filter(person_id__in=person_ids, team_id=team_id)
        .values_list("feature_flag_key", "hash_key", "person_id"),
        key=lambda x: 1 if person_id_to_distinct_id.get(x[2], "") == distinct_ids[0] else -1,
        # We want the highest priority to go last in sort order, so it's the latest update in the dict
    ):
        feature_flag_to_key_overrides[feature_flag] = override

    return feature_flag_to_key_overrides


# Return a Dict with all flags and their values
def _get_all_feature_flags(
    feature_flags: list[FeatureFlag],
    team_id: int,
    project_id: int,
    distinct_id: str,
    person_overrides: Optional[dict[str, str]] = None,
    groups: Optional[dict[GroupTypeName, str]] = None,
    property_value_overrides: Optional[dict[str, Union[str, int]]] = None,
    group_property_value_overrides: Optional[dict[str, dict[str, Union[str, int]]]] = None,
    skip_database_flags: bool = False,
) -> tuple[
    dict[str, Union[str, bool]], dict[str, dict], dict[str, object], bool, Optional[dict[str, FeatureFlagDetails]]
]:
    if group_property_value_overrides is None:
        group_property_value_overrides = {}
    if property_value_overrides is None:
        property_value_overrides = {}
    if groups is None:
        groups = {}
    cache = FlagsMatcherCache(project_id)

    if feature_flags:
        return FeatureFlagMatcher(
            team_id,
            project_id,
            feature_flags,
            distinct_id,
            groups,
            cache,
            person_overrides or {},
            property_value_overrides,
            group_property_value_overrides,
            skip_database_flags,
        ).get_matches_with_details()

    return {}, {}, {}, False, None


# Return feature flags
def get_all_feature_flags(
    team: Team,
    distinct_id: str,
    groups: Optional[dict[GroupTypeName, str]] = None,
    hash_key_override: Optional[str] = None,
    property_value_overrides: Optional[dict[str, Union[str, int]]] = None,
    group_property_value_overrides: Optional[dict[str, dict[str, Union[str, int]]]] = None,
    flag_keys: Optional[list[str]] = None,
) -> tuple[dict[str, Union[str, bool]], dict[str, dict], dict[str, object], bool]:
    all_flags, reasons, payloads, errors, _ = get_all_feature_flags_with_details(
        team,
        distinct_id,
        groups,
        hash_key_override,
        property_value_overrides,
        group_property_value_overrides,
        flag_keys,
    )
    return all_flags, reasons, payloads, errors


def get_all_feature_flags_with_details(
    team: Team,
    distinct_id: str,
    groups: Optional[dict[GroupTypeName, str]] = None,
    hash_key_override: Optional[str] = None,
    property_value_overrides: Optional[dict[str, Union[str, int]]] = None,
    group_property_value_overrides: Optional[dict[str, dict[str, Union[str, int]]]] = None,
    flag_keys: Optional[list[str]] = None,
    only_evaluate_survey_feature_flags: bool = False,  # If True, only evaluate flags starting with SURVEY_TARGETING_FLAG_PREFIX
) -> tuple[
    dict[str, Union[str, bool]], dict[str, dict], dict[str, object], bool, Optional[dict[str, FeatureFlagDetails]]
]:
    if group_property_value_overrides is None:
        group_property_value_overrides = {}
    if property_value_overrides is None:
        property_value_overrides = {}
    if groups is None:
        groups = {}
    property_value_overrides, group_property_value_overrides = add_local_person_and_group_properties(
        distinct_id, groups, property_value_overrides, group_property_value_overrides
    )
    feature_flags_to_be_evaluated = get_feature_flags_for_team_in_cache(team.project_id)
    cache_hit = True

    if feature_flags_to_be_evaluated is None:
        cache_hit = False
        feature_flags_to_be_evaluated = set_feature_flags_for_team_in_cache(team.project_id)

    # Filter flags by keys if provided
    if flag_keys is not None and not only_evaluate_survey_feature_flags:
        flag_keys_set = set(flag_keys)
        feature_flags_to_be_evaluated = [ff for ff in feature_flags_to_be_evaluated if ff.key in flag_keys_set]
    # NB: this behavior is posthog-js specific, and is controlled by the advanced_only_evaluate_survey_feature_flags config parameter
    elif only_evaluate_survey_feature_flags:
        feature_flags_to_be_evaluated = [
            ff for ff in feature_flags_to_be_evaluated if ff.key.startswith(SURVEY_TARGETING_FLAG_PREFIX)
        ]

    FLAG_CACHE_HIT_COUNTER.labels(team_id=label_for_team_id_to_track(team.id), cache_hit=cache_hit).inc()

    flags_have_experience_continuity_enabled = any(
        feature_flag.ensure_experience_continuity for feature_flag in feature_flags_to_be_evaluated
    )

    is_database_alive = not settings.DECIDE_SKIP_POSTGRES_FLAGS
    if not is_database_alive or not flags_have_experience_continuity_enabled:
        return _get_all_feature_flags(
            feature_flags_to_be_evaluated,
            team.id,
            team.project_id,
            distinct_id,
            groups=groups,
            property_value_overrides=property_value_overrides,
            group_property_value_overrides=group_property_value_overrides,
            skip_database_flags=not is_database_alive,
        )

    # For flags with experience continuity enabled, we want a consistent distinct_id that doesn't change,
    # no matter what other distinct_ids the user has.
    # FeatureFlagHashKeyOverride stores a distinct_id (hash_key_override) given a flag, person_id, and team_id.
    should_write_hash_key_override = False
    writing_hash_key_override = False
    # This is the write-path for experience continuity flags. When a hash_key_override is sent to decide,
    # we want to store it in the database, and then use it in the read-path to get flags with experience continuity enabled.
    if hash_key_override is not None and not settings.DECIDE_SKIP_HASH_KEY_OVERRIDE_WRITES:
        # First, check if the hash_key_override is already in the database.
        # We don't have to check this in an ideal world, but read replica operations are much more resilient than write operations.
        # So, if an extra query check helps us avoid the write path, it's worth it.

        try:
            with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS, DATABASE_FOR_FLAG_MATCHING) as cursor:
                distinct_ids = [distinct_id, str(hash_key_override)]
                query = """
                    WITH target_person_ids AS (
                        SELECT team_id, person_id FROM posthog_persondistinctid WHERE team_id = %(team_id)s AND
                        distinct_id = ANY(%(distinct_ids)s)
                    ),
                    existing_overrides AS (
                        SELECT team_id, person_id, feature_flag_key, hash_key FROM posthog_featureflaghashkeyoverride
                        WHERE team_id = %(team_id)s AND person_id IN (SELECT person_id FROM target_person_ids)
                    )
                    SELECT key FROM posthog_featureflag flag
                    JOIN posthog_team team ON flag.team_id = team.id
                    WHERE team.project_id = %(project_id)s
                        AND flag.ensure_experience_continuity = TRUE AND flag.active = TRUE AND flag.deleted = FALSE
                        AND key NOT IN (SELECT feature_flag_key FROM existing_overrides)
                """
                cursor.execute(
                    query,
                    {"team_id": team.id, "project_id": team.project_id, "distinct_ids": distinct_ids},
                )
                flags_with_no_overrides = [row[0] for row in cursor.fetchall()]
                should_write_hash_key_override = len(flags_with_no_overrides) > 0
        except Exception as e:
            handle_feature_flag_exception(e, "[Feature Flags] Error figuring out hash key overrides")

        if should_write_hash_key_override:
            try:
                hash_key_override = str(hash_key_override)

                # :TRICKY: There are a few cases for write we need to handle:
                # 1. Ingestion delay causing the person to not have been created yet or the distinct_id not yet associated
                # 2. Merging of two different already existing persons, which results in 1 person_id being deleted and ff hash key overrides to be moved.
                # 3. Person being deleted via UI or API (this is rare)
                #
                # In all cases, we simply try to find all personIDs associated with the distinct_id
                # and the hash_key_override, and add overrides for all these personIDs.
                # On merge, if a person is deleted, it is fine because the below line in plugin-server will take care of it.
                # https://github.com/PostHog/posthog/blob/master/plugin-server/src/utils/db/db.ts (updateCohortsAndFeatureFlagsForMerge)

                writing_hash_key_override = set_feature_flag_hash_key_overrides(
                    team, [distinct_id, hash_key_override], hash_key_override
                )
                team_id_label = label_for_team_id_to_track(team.id)
                FLAG_HASH_KEY_WRITES_COUNTER.labels(
                    team_id=team_id_label,
                    successful_write=writing_hash_key_override,
                ).inc()
            except Exception as e:
                # If the database is in read-only mode, we can't handle experience continuity flags,
                # since the set_feature_flag_hash_key_overrides call will fail.

                # For this case, and for any other case, do not error out on decide, just continue assuming continuity couldn't happen.
                # At the same time, don't set db down, because the read-replica might still be up.
                handle_feature_flag_exception(
                    e,
                    "[Feature Flags] Error while setting feature flag hash key overrides",
                    set_healthcheck=False,
                )

    # This is the read-path for experience continuity. We need to get the overrides, and to do that, we get the person_id.
    using_database = None
    try:
        # when we're writing a hash_key_override, we query the main database, not the replica
        # this is because we need to make sure the write is successful before we read it
        using_database = WRITE_DATABASE_FOR_PERSONS if writing_hash_key_override else READ_ONLY_DATABASE_FOR_PERSONS
        person_overrides = {}
        with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS, using_database):
            target_distinct_ids = [distinct_id]
            if hash_key_override is not None:
                target_distinct_ids.append(str(hash_key_override))
            person_overrides = get_feature_flag_hash_key_overrides(team.id, target_distinct_ids, using_database)

    except Exception as e:
        handle_feature_flag_exception(
            e,
            f"[Feature Flags] Error fetching hash key overrides from {using_database} db",
            set_healthcheck=not writing_hash_key_override,
        )
        # database is down, we can't handle experience continuity flags at all.
        # Treat this same as if there are no experience continuity flags.
        # This automatically sets 'errorsWhileComputingFlags' to True.
        return _get_all_feature_flags(
            feature_flags_to_be_evaluated,
            team.id,
            team.project_id,
            distinct_id,
            groups=groups,
            property_value_overrides=property_value_overrides,
            group_property_value_overrides=group_property_value_overrides,
            skip_database_flags=True,
        )

    return _get_all_feature_flags(
        feature_flags_to_be_evaluated,
        team.id,
        team.project_id,
        distinct_id,
        person_overrides,
        groups=groups,
        property_value_overrides=property_value_overrides,
        group_property_value_overrides=group_property_value_overrides,
    )


def set_feature_flag_hash_key_overrides(team: Team, distinct_ids: list[str], hash_key_override: str) -> bool:
    # As a product decision, the first override wins, i.e consistency matters for the first walkthrough.
    # Thus, we don't need to do upserts here.

    # We have retries for race conditions with person merging and deletion, if a person is deleted, retry, because
    # the distinct IDs might have moved to the new person, without the appropriate overrides.
    max_retries = 2
    retry_delay = 0.1  # seconds

    for retry in range(max_retries):
        try:
            # make the entire hash key override logic a single transaction
            # with a small timeout
            with execute_with_timeout(FLAG_MATCHING_QUERY_TIMEOUT_MS) as cursor:
                query = """
                    WITH target_person_ids AS (
                        SELECT team_id, person_id FROM posthog_persondistinctid WHERE team_id = %(team_id)s AND
                        distinct_id = ANY(%(distinct_ids)s)
                    ),
                    existing_overrides AS (
                        SELECT team_id, person_id, feature_flag_key, hash_key FROM posthog_featureflaghashkeyoverride
                        WHERE team_id = %(team_id)s AND person_id IN (SELECT person_id FROM target_person_ids)
                    ),
                    flags_to_override AS (
                        SELECT key FROM posthog_featureflag flag
                        JOIN posthog_team team ON flag.team_id = team.id
                        WHERE team.project_id = %(project_id)s
                            AND flag.ensure_experience_continuity = TRUE AND flag.active = TRUE AND flag.deleted = FALSE
                            AND flag.key NOT IN (SELECT feature_flag_key FROM existing_overrides)
                    )
                    INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                        SELECT team_id, person_id, key, %(hash_key_override)s
                        FROM flags_to_override, target_person_ids
                        WHERE EXISTS (SELECT 1 FROM posthog_person WHERE id = person_id AND team_id = %(team_id)s)
                        ON CONFLICT DO NOTHING
                """
                # The EXISTS clause is to make sure we don't try to add overrides for deleted persons, as this results in erroring out.

                # :TRICKY: regarding the ON CONFLICT DO NOTHING clause:
                # This can happen if the same person is being processed by multiple workers
                # / we got multiple requests for the same person at the same time. In this case, we can safely ignore the error
                # because they're all trying to add the same overrides.
                # We don't want to return an error response for `/decide` just because of this.
                # There can be cases where it's a different override (like a person on two different browser sending the same request at the same time),
                # but we don't care about that case because first override wins.
                cursor.execute(
                    query,
                    {
                        "team_id": team.id,
                        "project_id": team.project_id,
                        "distinct_ids": distinct_ids,
                        "hash_key_override": hash_key_override,
                    },
                )
                return cursor.rowcount > 0

        except IntegrityError as e:
            if "violates foreign key constraint" in str(e) and retry < max_retries - 1:
                # This can happen if a person is deleted while we're trying to add overrides for it.
                # This is the only case when we retry.
                logger.info(
                    "Retrying set_feature_flag_hash_key_overrides due to person deletion",
                    exc_info=True,
                )
                time.sleep(retry_delay)
            else:
                raise

    return False


def handle_feature_flag_exception(err: Exception, log_message: str = "", set_healthcheck: bool = True):
    logger.exception(log_message)
    reason = parse_exception_for_error_message(err)
    FLAG_EVALUATION_ERROR_COUNTER.labels(reason=reason).inc()
    if reason == "unknown":
        capture_exception(err)


def parse_exception_for_error_message(err: Exception):
    reason = "unknown"
    if isinstance(err, DatabaseError):
        if "statement timeout" in str(err):
            reason = "timeout"
        elif "no more connections" in str(err):
            reason = "no_more_connections"
        elif "Failed to fetch conditions" in str(err):
            reason = "flag_condition_retry"
        elif "Failed to fetch group" in str(err):
            reason = "group_mapping_retry"
        elif "Database healthcheck failed" in str(err):
            reason = "healthcheck_failed"
        elif "query_wait_timeout" in str(err):
            reason = "query_wait_timeout"

    return reason


def key_and_field_for_property(property: Property) -> tuple[str, str]:
    column = "group_properties" if property.type == "group" else "properties"
    key = property.key
    sanitized_key = sanitize_property_key(key)

    return (
        f"{column}_{sanitized_key}_type",
        f"{column}__{key}",
    )


def get_all_properties_with_math_operators(
    properties: list[Property], cohorts_cache: dict[int, CohortOrEmpty], project_id: int
) -> list[tuple[str, str]]:
    all_keys_and_fields = []

    for prop in properties:
        if prop.type == "cohort":
            cohort_id = int(cast(Union[str, int], prop.value))
            if cohorts_cache.get(cohort_id) is None:
                queried_cohort = (
                    Cohort.objects.db_manager(DATABASE_FOR_FLAG_MATCHING)
                    .filter(pk=cohort_id, team__project_id=project_id, deleted=False)
                    .first()
                )
                cohorts_cache[cohort_id] = queried_cohort or ""

            cohort = cohorts_cache[cohort_id]
            if cohort:
                all_keys_and_fields.extend(
                    get_all_properties_with_math_operators(cohort.properties.flat, cohorts_cache, project_id)
                )
        elif prop.operator in ["gt", "lt", "gte", "lte"] and prop.type in ("person", "group"):
            all_keys_and_fields.append(key_and_field_for_property(prop))

    return all_keys_and_fields


def add_local_person_and_group_properties(distinct_id, groups, person_properties, group_properties):
    all_person_properties = {"distinct_id": distinct_id, **(person_properties or {})}

    all_group_properties = {}
    if groups:
        for group_name in groups:
            all_group_properties[group_name] = {
                "$group_key": groups[group_name],
                **(group_properties.get(group_name) or {}),
            }

    return all_person_properties, all_group_properties


def check_pure_is_not_operator_condition(condition: dict) -> bool:
    properties = condition.get("properties", [])
    if properties and all(prop.get("operator") in ("is_not_set", "is_not") for prop in properties):
        return True
    return False


def check_flag_evaluation_query_is_ok(feature_flag: FeatureFlag, project_id: int) -> bool:
    # TRICKY: There are some cases where the regex is valid re2 syntax, but postgresql doesn't like it.
    # This function tries to validate such cases. See `test_cant_create_flag_with_data_that_fails_to_query` for an example.
    # It however doesn't catch all cases, like when the property doesn't exist on any person, which shortcircuits regex evaluation
    # so it's not a guarantee that the query will work.

    # This is a very rough simulation of the actual query that will be run.
    # Only reason we do it this way is to catch any DB level errors that will bork at runtime
    # but aren't caught by above validation, like a regex valid according to re2 but not postgresql.
    # We also randomly query for 20 people sans distinct id to make sure the query is valid.

    # TODO: Once we move to no DB level evaluation, can get rid of this.

    group_type_index = feature_flag.aggregation_group_type_index

    base_query: QuerySet = (
        Person.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(team__project_id=project_id)
        if group_type_index is None
        else Group.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(
            team__project_id=project_id, group_type_index=group_type_index
        )
    )
    query_fields = []

    for index, condition in enumerate(feature_flag.conditions):
        key = f"flag_0_condition_{index}"
        property_list = Filter(data=condition).property_groups.flat
        expr = properties_to_Q(
            project_id,
            property_list,
        )
        properties_with_math_operators = get_all_properties_with_math_operators(property_list, {}, project_id)
        type_property_annotations = _get_property_type_annotations(properties_with_math_operators)
        base_query = base_query.annotate(
            **type_property_annotations,
            **{
                key: ExpressionWrapper(
                    cast(Expression, expr if expr else RawSQL("true", [])),
                    output_field=BooleanField(),
                ),
            },
        )
        query_fields.append(key)

    values = base_query.values(*query_fields)[:10]
    return len(values) > 0


def _get_property_type_annotations(properties_with_math_operators):
    return {
        prop_key: Func(F(prop_field), function="JSONB_TYPEOF", output_field=CharField())
        for prop_key, prop_field in properties_with_math_operators
    }
