import re
import time
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Optional, Union, cast
from uuid import UUID

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models, transaction
from django.db.models import Q, QuerySet
from django.db.models.expressions import F
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.constants import PropertyOperatorType
from posthog.exceptions_capture import capture_exception
from posthog.helpers.batch_iterators import ArrayBatchIterator, BatchIterator, FunctionBatchIterator
from posthog.models.file_system.constants import DEFAULT_SURFACE
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.models.person.util import get_person_by_uuid, get_person_ids_and_uuids_by_uuids
from posthog.models.property import Property, PropertyGroup
from posthog.models.utils import RootTeamManager, RootTeamMixin, sane_repr
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.schema_enums import ProductKey
from posthog.settings.base_variables import TEST

if TYPE_CHECKING:
    from posthog.models.team import Team


class CohortKind(StrEnum):
    INTERNAL_TEST_USERS = "internal_test_users"


class CohortType(StrEnum):
    STATIC = "static"
    PERSON_PROPERTY = "person_property"
    BEHAVIORAL = "behavioral"
    REALTIME = "realtime"
    ANALYTICAL = "analytical"


# The empty string literal helps us determine when the cohort is invalid/deleted, when
# set in cohorts_cache
CohortOrEmpty = Union["Cohort", Literal[""], None]

# Maximum person count for a cohort to be eligible for real-time evaluation
# Cohorts with more than 20M persons cannot be real-time due to system limitations
REALTIME_COHORT_MAX_PERSON_COUNT = 20_000_000

logger = structlog.get_logger(__name__)

DEFAULT_COHORT_INSERT_BATCH_SIZE = 1000


class Group:
    def __init__(
        self,
        properties: Optional[dict[str, Any]] = None,
        action_id: Optional[int] = None,
        event_id: Optional[str] = None,
        days: Optional[int] = None,
        count: Optional[int] = None,
        count_operator: Optional[Literal["eq", "lte", "gte"]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        label: Optional[str] = None,
    ):
        if not properties and not action_id and not event_id:
            raise ValueError("Cohort group needs properties or action_id or event_id")
        self.properties = properties
        self.action_id = action_id
        self.event_id = event_id
        self.label = label
        self.days = days
        self.count = count
        self.count_operator = count_operator
        self.start_date = start_date
        self.end_date = end_date

    def to_dict(self) -> dict[str, Any]:
        dup = self.__dict__.copy()
        dup["start_date"] = self.start_date.isoformat() if self.start_date else self.start_date
        dup["end_date"] = self.end_date.isoformat() if self.end_date else self.end_date
        return dup


class CohortManager(RootTeamManager):
    def create(self, *args: Any, **kwargs: Any):
        if kwargs.get("groups"):
            kwargs["groups"] = [Group(**group).to_dict() for group in kwargs["groups"]]
        cohort = super().create(*args, **kwargs)
        return cohort


# Fields that are updated during cohort recalculation. The save_fields lists
# in _safe_save_cohort_state must remain subsets of this set, otherwise the
# is_cohort_recalculation_only_save guard will incorrectly allow signal handlers to fire.
COHORT_RECALCULATION_FIELDS = frozenset(
    {"is_calculating", "last_calculation", "errors_calculating", "last_error_at", "count"}
)


def is_cohort_recalculation_only_save(kwargs: dict) -> bool:
    """Return True when a post_save signal was triggered only by recalculation bookkeeping fields."""
    update_fields = kwargs.get("update_fields")
    return update_fields is not None and COHORT_RECALCULATION_FIELDS.issuperset(update_fields)


class Cohort(FileSystemSyncMixin, RootTeamMixin, models.Model):
    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.CharField(max_length=1000, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    deleted = models.BooleanField(default=False)
    filters = models.JSONField(
        null=True,
        blank=True,
        help_text="""Filters for the cohort. The `negation` field shown below is specific to
        cohort definitions (the inner sub-filters that build a cohort). Property filters used
        *outside* cohort definitions — e.g. on `team.test_account_filters`, insight filters, or
        feature flag conditions — must use `operator: "in"`/`"not_in"` for cohort exclusion and
        do NOT accept `negation`.

        Examples:

        # Behavioral filter (performed event)
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "OR",
                    "values": [{
                        "key": "address page viewed",
                        "type": "behavioral",
                        "value": "performed_event",
                        "negation": false,
                        "event_type": "events",
                        "time_value": "30",
                        "time_interval": "day"
                    }]
                }]
            }
        }

        # Person property filter
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [{
                        "key": "promoCodes",
                        "type": "person",
                        "value": ["1234567890"],
                        "negation": false,
                        "operator": "exact"
                    }]
                }]
            }
        }

        # Cohort filter (inner — within a cohort definition)
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [{
                        "key": "id",
                        "type": "cohort",
                        "value": 8814,
                        "negation": false
                    }]
                }]
            }
        }""",
    )
    query = models.JSONField(null=True, blank=True)
    people = models.ManyToManyField("posthog.Person", through="CohortPeople")  # type: models.ManyToManyField
    version = models.IntegerField(blank=True, null=True)
    pending_version = models.IntegerField(blank=True, null=True)
    count = models.IntegerField(blank=True, null=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, blank=True, null=True)

    is_calculating = models.BooleanField(default=False)
    last_calculation = models.DateTimeField(blank=True, null=True)
    last_calculation_duration_ms = models.IntegerField(blank=True, null=True)
    errors_calculating = models.IntegerField(default=0)
    last_error_at = models.DateTimeField(blank=True, null=True)
    last_backfill_person_properties_at = models.DateTimeField(blank=True, null=True)
    last_backfill_events_at = models.DateTimeField(blank=True, null=True)
    last_realtime_cohort_calculation_at = models.DateTimeField(blank=True, null=True)

    is_static = models.BooleanField(default=False)
    kind = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=[(kind.value, kind.value) for kind in CohortKind],
        help_text="System-defined cohort kind. Null for user-created cohorts.",
    )

    cohort_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=[(cohort_type.value, cohort_type.value) for cohort_type in CohortType],
        help_text="Type of cohort based on filter complexity",
    )

    # deprecated in favor of filters
    groups = models.JSONField(default=list)

    objects = CohortManager()  # type: ignore

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "kind"],
                condition=models.Q(kind__isnull=False, deleted=False),
                name="unique_cohort_kind_per_team",
            ),
        ]
        indexes = [
            # Backs the default list ordering (filter by team, order by -created_at).
            models.Index(fields=["team", "-created_at"], name="cohort_team_created_idx"),
            # Backs `name__icontains` search (the cohort picker's server-side search).
            GinIndex(fields=["name"], name="cohort_name_trgm_idx", opclasses=["gin_trgm_ops"]),
        ]
        db_table = "posthog_cohort"

    def __str__(self):
        return self.name or "Untitled cohort"

    @classmethod
    def get_file_system_unfiled(cls, team: "Team", surface: str = DEFAULT_SURFACE) -> QuerySet["Cohort"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="cohort", ref_field="id", surface=surface)

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Cohorts"),
            type="cohort",  # sync with APIScopeObject in scopes.py
            ref=str(self.pk),
            name=self.name or "Untitled",
            href=f"/cohorts/{self.pk}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=self.deleted,
        )

    def _has_filter_type(self, filter_type: str) -> bool:
        """Check whether the cohort's filter tree contains any leaf node of the given type."""
        if not self.filters:
            return False
        properties = self.filters.get("properties")
        if not properties:
            return False

        def _check(node) -> bool:
            if not isinstance(node, dict):
                return False
            node_type = node.get("type")
            if node_type in ("AND", "OR"):
                return any(_check(child) for child in node.get("values", []))
            return node_type == filter_type

        return _check(properties)

    @property
    def is_flag_compatible(self) -> bool:
        """Whether this cohort can be used in feature flag targeting via cohort_membership lookups.

        Gates on both person property and event backfills based on which filter types the cohort uses:
        - Cohorts with person property filters require last_backfill_person_properties_at
        - Cohorts with behavioral event filters require last_backfill_events_at
        - Cohorts with both require both timestamps
        - Cohorts with neither recognized filter type (empty filters, cohort-reference-only, etc.)
          are not flag-compatible, even if stale timestamps are set, because HogQLRealtimeCohortQuery
          cannot evaluate them.
        """
        if self.cohort_type != CohortType.REALTIME:
            return False

        has_person_filters = self._has_filter_type("person")
        has_behavioral_filters = self._has_filter_type("behavioral")

        if not (has_person_filters or has_behavioral_filters):
            return False

        if has_person_filters and self.last_backfill_person_properties_at is None:
            return False
        if has_behavioral_filters and self.last_backfill_events_at is None:
            return False

        return True

    @property
    def properties(self) -> PropertyGroup:
        if self.filters:
            # Do not try simplifying properties at this stage. We'll let this happen at query time.
            return Filter(data={**self.filters, "is_simplified": True}).property_groups

        # convert deprecated groups to properties
        if self.groups:
            property_groups = []
            for group in self.groups:
                if group.get("properties"):
                    # KLUDGE: map 'event' to 'person' to handle faulty event type that
                    # used to be saved for old properties
                    # TODO: Remove once the event type is swapped over
                    props = group.get("properties")
                    if isinstance(props, list):
                        for prop in props:
                            if prop.get("type", "event") == "event":
                                prop["type"] = "person"
                    elif isinstance(props, dict) and "type" not in props and "values" not in props:
                        # these are old-old properties
                        # of the form {'key': 'value'}.
                        # It's implicit here that they're all event types
                        # so we convert them to a list
                        new_properties = []
                        for key, value in props.items():
                            new_properties.append({"key": key, "value": value, "type": "person"})

                        group["properties"] = new_properties

                    # Do not try simplifying properties at this stage. We'll let this happen at query time.
                    property_groups.append(Filter(data={**group, "is_simplified": True}).property_groups)
                elif group.get("action_id") or group.get("event_id"):
                    key = group.get("action_id") or group.get("event_id")
                    event_type: Literal["actions", "events"] = "actions" if group.get("action_id") else "events"
                    try:
                        count = max(0, int(group.get("count") or 0))
                    except ValueError:
                        count = 0

                    property_groups.append(
                        PropertyGroup(
                            PropertyOperatorType.AND,
                            [
                                Property(
                                    key=key,
                                    type="behavioral",
                                    value="performed_event_multiple" if count else "performed_event",
                                    event_type=event_type,
                                    time_interval="day",
                                    time_value=group.get("days") or 365,
                                    operator=group.get("count_operator"),
                                    operator_value=count,
                                )
                            ],
                        )
                    )
                else:
                    # invalid state
                    return PropertyGroup(PropertyOperatorType.AND, cast(list[Property], []))

            return PropertyGroup(PropertyOperatorType.OR, property_groups)

        return PropertyGroup(PropertyOperatorType.AND, cast(list[Property], []))

    def get_analytics_metadata(self):
        return {
            "filters": self.properties.to_dict(),
            "name_length": len(self.name) if self.name else 0,
            "deleted": self.deleted,
        }

    def _safe_reset_calculating_state(self, completed_version: int) -> None:
        """
        Safely reset is_calculating flag only when it's appropriate.
        This prevents the flag from being reset while higher-version calculations are still running.

        Args:
            completed_version: The version that just completed calculating
        """
        # Use atomic update to safely check and reset is_calculating flag
        # Only reset if the completed version is >= the current pending_version
        Cohort.objects.filter(pk=self.pk, pending_version__lte=completed_version, is_calculating=True).update(
            is_calculating=False
        )

    def calculate_people_ch(self, pending_version: int, *, initiating_user_id: Optional[int] = None):
        from products.cohorts.backend.models.util import recalculate_cohortpeople

        logger.info(
            "cohort_calculation_started",
            id=self.pk,
            current_version=self.version,
            new_version=pending_version,
        )
        start_time = time.monotonic()

        cohort_type_cleared = False
        try:
            count = recalculate_cohortpeople(self, pending_version, initiating_user_id=initiating_user_id)
            self.count = count

            # Clear cohort_type if count exceeds the realtime threshold
            if self.cohort_type == CohortType.REALTIME and count and count > REALTIME_COHORT_MAX_PERSON_COUNT:
                self.cohort_type = None
                cohort_type_cleared = True

            # Update version inside the try block so it can't be skipped by finally exceptions.
            # Conditional filter preserves concurrency safety: lower versions don't overwrite higher ones.
            version_update_fields: dict[str, Any] = {"version": pending_version, "count": count}
            if cohort_type_cleared:
                version_update_fields["cohort_type"] = None
            Cohort.objects.filter(pk=self.pk).filter(Q(version__lt=pending_version) | Q(version__isnull=True)).update(
                **version_update_fields
            )

            self.last_calculation = timezone.now()
            self.errors_calculating = 0
            self.last_error_at = None
        except Exception:
            self.errors_calculating = F("errors_calculating") + 1
            self.last_error_at = timezone.now()

            logger.warning(
                "cohort_calculation_failed",
                id=self.pk,
                current_version=self.version,
                new_version=pending_version,
                exc_info=True,
            )

            raise
        finally:
            # Save fields modified during calculation, but exclude is_calculating to prevent race condition
            self.save(
                update_fields=["last_calculation", "errors_calculating", "last_error_at", "cohort_type", "groups"]
            )
            # Only set is_calculating = False if this is the highest pending version
            # This prevents the flag from being reset while other higher-version calculations are still running
            self._safe_reset_calculating_state(completed_version=pending_version)

        self.refresh_from_db()

        logger.info(
            "cohort_calculation_completed",
            id=self.pk,
            version=pending_version,
            duration=(time.monotonic() - start_time),
        )

    def insert_users_by_list(
        self,
        items: list[str],
        *,
        team_id: Optional[int] = None,
        batch_size: int = DEFAULT_COHORT_INSERT_BATCH_SIZE,
    ) -> int:
        """
        Insert a list of users identified by their distinct ID into the cohort, for the given team.

        Args:
            items: List of distinct IDs of users to be inserted into the cohort.
            team_id: ID of the team for which to insert the users. Defaults to `self.team`, because of a lot of existing usage in tests.
            batch_size: Number of records to process in each batch. Defaults to 1000.
        """
        if team_id is None:
            team_id = self.team_id

        if TEST:
            from posthog.test.base import flush_persons_and_events

            # Make sure persons are created in tests before running this
            flush_persons_and_events()

        def create_uuid_batch(batch_index: int, batch_size: int) -> list[str]:
            from posthog.models.person.util import get_person_uuids_by_distinct_ids

            start_idx = batch_index * batch_size
            end_idx = start_idx + batch_size
            with personhog_caller_tag("cohorts/uuid-batch"):
                return get_person_uuids_by_distinct_ids(team_id, items[start_idx:end_idx])

        batch_iterator = FunctionBatchIterator(create_uuid_batch, batch_size=batch_size, max_items=len(items))
        return self._insert_users_list_with_batching(batch_iterator, insert_in_clickhouse=True, team_id=team_id)

    def insert_users_list_by_uuid(
        self,
        items: list[str],
        batchsize=DEFAULT_COHORT_INSERT_BATCH_SIZE,
        *,
        team_id: int,
        raise_on_error: bool = False,
    ) -> int:
        """
        Insert a list of users identified by their UUID into the cohort, for the given team.

        Args:
            items: List of user UUIDs to be inserted into the cohort.
            batchsize: Number of UUIDs to process in each batch.
            team_id: The ID of the team to which the cohort belongs.
            raise_on_error: When True, a batch insert failure is re-raised and terminal
                cohort state is left for the caller to finalize, instead of being swallowed
                and recorded on the cohort here. Use when the caller records its own
                success/failure outcome and must not treat a partial insert as success.

        Returns:
            The number of batches processed.
        """

        batch_iterator = ArrayBatchIterator(items, batch_size=batchsize)
        return self._insert_users_list_with_batching(
            batch_iterator, insert_in_clickhouse=True, team_id=team_id, raise_on_error=raise_on_error
        )

    def insert_users_list_by_id_uuid_pairs(
        self,
        items: list[tuple[int, str]],
        *,
        team_id: int,
        raise_on_error: bool = False,
    ) -> int:
        """
        Insert already-resolved (person_id, person_uuid) members into the cohort, for the given team.

        Skips the per-batch UUID → person id resolution that ``insert_users_list_by_uuid``
        performs — for callers that resolved the persons themselves (e.g. a validation pass over
        the same set) and must not pay for a second personhog lookup. Semantics otherwise match
        ``insert_users_list_by_uuid``, including ``raise_on_error``.

        Returns:
            The number of batches processed.
        """
        batch_iterator = ArrayBatchIterator(items, batch_size=DEFAULT_COHORT_INSERT_BATCH_SIZE)
        return self._insert_users_list_with_batching(
            batch_iterator,
            insert_in_clickhouse=True,
            team_id=team_id,
            raise_on_error=raise_on_error,
            insert_batch=lambda batch: self._insert_resolved_batch(batch, insert_in_clickhouse=True, team_id=team_id),
        )

    def insert_users_by_email(
        self,
        items: list[str],
        *,
        team_id: Optional[int] = None,
        batch_size: int = DEFAULT_COHORT_INSERT_BATCH_SIZE,
        email_property_key: str | None = None,
    ) -> int:
        """
        Insert a list of users identified by their email address into the cohort, for the given team.
        Args:
            items: List of email addresses of users to be inserted into the cohort.
            team_id: ID of the team for which to insert the users. Defaults to `self.team`, because of a lot of existing usage in tests.
            batch_size: Number of records to process in each batch. Defaults to 1000.
            email_property_key: Accepted for backwards compatibility but ignored — all lookups
                                use the ClickHouse pmat_email materialized column.
        """
        if team_id is None:
            team_id = self.team_id

        if TEST:
            from posthog.test.base import flush_persons_and_events

            # Make sure persons are created in tests before running this
            flush_persons_and_events()

        def create_uuid_batch(batch_index: int, batch_size: int) -> list[str]:
            start_idx = batch_index * batch_size
            end_idx = start_idx + batch_size
            return self._get_uuids_for_emails_batch_ch(items[start_idx:end_idx], team_id)

        batch_iterator = FunctionBatchIterator(create_uuid_batch, batch_size=batch_size, max_items=len(items))
        return self._insert_users_list_with_batching(batch_iterator, insert_in_clickhouse=True, team_id=team_id)

    def _get_uuids_for_emails_batch_ch(self, emails: list[str], team_id: int) -> list[str]:
        if not emails:
            return []

        query = """
        SELECT person.id
        FROM person
        WHERE person.team_id = %(team_id)s
          AND person.pmat_email IN %(emails)s
        GROUP BY person.id
        HAVING argMax(person.is_deleted, person.version) = 0
        SETTINGS optimize_aggregation_in_order = 1
        """

        tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
        result = sync_execute(query, {"team_id": team_id, "emails": emails})
        return [str(row[0]) for row in result]

    def insert_users_list_by_uuid_into_pg_only(
        self,
        items: list[str],
        team_id: int,
    ) -> int:
        """
        Insert users into Postgres cohortpeople table ONLY (not ClickHouse).
        This method exists solely to support syncing from ClickHouse to Postgres
        after cohort calculations. Do not use for normal cohort operations.

        Used by: insert_cohort_people_into_pg
        """

        batch_iterator = ArrayBatchIterator(items, batch_size=DEFAULT_COHORT_INSERT_BATCH_SIZE)
        return self._insert_users_list_with_batching(batch_iterator, insert_in_clickhouse=False, team_id=team_id)

    def _insert_users_list_with_batching(
        self,
        batch_iterator: BatchIterator[Any],
        insert_in_clickhouse: bool = False,
        *,
        team_id: int,
        raise_on_error: bool = False,
        insert_batch: Callable[[list[Any]], None] | None = None,
    ) -> int:
        """
        Insert a list of users identified by their UUID into the cohort, for the given team.

        Args:
            batch_iterator: BatchIterator of user UUIDs to be inserted into the cohort.
            insert_in_clickhouse: Whether the data should also be inserted into ClickHouse.
            team_id: The ID of the team to which the cohort belongs.
            insert_batch: Override for the per-batch write. Defaults to resolving each batch of
                UUIDs via personhog and inserting (``_insert_batch_via_personhog``, which honors
                ``insert_in_clickhouse``); callers whose batches are not plain UUID lists supply
                a writer matching their item type.

        Returns:
            Number of batches processed.
        """
        from products.cohorts.backend.models.util import count_cohort_members

        def _resolve_and_insert_batch(batch: list[Any]) -> None:
            self._insert_batch_via_personhog(batch, insert_in_clickhouse, team_id=team_id)

        insert_batch = insert_batch or _resolve_and_insert_batch

        current_batch_index = -1
        processing_error = None
        try:
            for batch_index, batch in batch_iterator:
                current_batch_index = batch_index
                insert_batch(batch)

        except SoftTimeLimitExceeded as err:
            # Let a Celery soft-time-limit interruption propagate so the task's time limit
            # actually bounds the run. Swallowing it here (as the broad except below would)
            # leaves the caller's loop running past the limit, since Celery raises it once.
            # Record it as a processing error so the finally marks the run as failed
            # rather than a successful calculation.
            processing_error = err
            raise
        except Exception as err:
            processing_error = err
            # When the caller owns terminal-state finalization (raise_on_error), surface
            # the failure instead of swallowing it, so a partial insert can't be recorded
            # as success. The finally block below skips its own error save in this mode.
            if settings.DEBUG or raise_on_error:
                raise
            capture_exception(
                err,
                additional_properties={
                    "cohort_id": self.id,
                    "team_id": team_id,
                    "batch_index": current_batch_index,
                },
            )
        finally:
            # Always update the count and cohort state, even if processing failed
            try:
                count = count_cohort_members(cohort_id=self.id, team_id=self.team_id, consistency="strong")
                self.count = count
            except Exception as count_err:
                # If count calculation fails, log the error but don't override the processing error.
                # Leave existing count unchanged - it's better than None.
                logger.exception(
                    "Failed to calculate static cohort size",
                    cohort_id=self.id,
                    team_id=team_id,
                )
                capture_exception(
                    count_err,
                    additional_properties={"cohort_id": self.id, "team_id": team_id},
                )

            # In raise_on_error mode the caller finalizes cohort state on failure, so skip
            # the error save here to avoid double-counting errors_calculating. The success
            # path (processing_error is None) still finalizes state as usual.
            if not (raise_on_error and processing_error is not None):
                self._safe_save_cohort_state(team_id=team_id, processing_error=processing_error)

        return current_batch_index + 1

    def _insert_batch_via_personhog(
        self,
        batch: list[str],
        insert_in_clickhouse: bool,
        *,
        team_id: int,
    ) -> None:
        """Personhog path for inserting a single batch of cohort members.

        Resolves UUIDs → person IDs via personhog (field-masked — membership only needs
        id/uuid, not properties or distinct IDs), then writes the resolved batch.
        """
        with personhog_caller_tag("cohorts/static-insert"):
            id_uuid_pairs = get_person_ids_and_uuids_by_uuids(team_id, batch)
        self._insert_resolved_batch(id_uuid_pairs, insert_in_clickhouse=insert_in_clickhouse, team_id=team_id)

    def _insert_resolved_batch(
        self,
        id_uuid_pairs: list[tuple[int, str]],
        *,
        insert_in_clickhouse: bool,
        team_id: int,
    ) -> None:
        """Write a single batch of already-resolved (person_id, person_uuid) cohort members.

        Calls the InsertCohortMembers RPC. ClickHouse inserts (if requested)
        exclude persons already in the cohort because the
        person_static_cohort table's ORDER BY includes a per-row UUID,
        preventing ReplacingMergeTree from deduplicating repeated inserts.
        """
        from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE

        from products.cohorts.backend.models.util import insert_cohort_members, insert_static_cohort

        if not id_uuid_pairs:
            return

        person_ids = [person_id for person_id, _ in id_uuid_pairs]
        person_uuids = [person_uuid for _, person_uuid in id_uuid_pairs]

        if insert_in_clickhouse:
            existing_uuids = self._get_existing_ch_member_uuids(person_uuids, team_id, PERSON_STATIC_COHORT_TABLE)
            new_uuids = [UUID(u) for u in person_uuids if u not in existing_uuids]
            if new_uuids:
                insert_static_cohort(new_uuids, self.pk, team_id=team_id)

        insert_cohort_members(team_id, self.pk, person_ids, self.version, _skip_ownership_check=True)

    def _get_existing_ch_member_uuids(
        self,
        person_uuids: list[str],
        team_id: int,
        table: str,
    ) -> set[str]:
        """Return the subset of person_uuids that already exist in the CH static cohort table."""
        if not person_uuids:
            return set()
        tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
        # nosemgrep: clickhouse-fstring-param-audit - table name from constant, values parameterized
        rows = sync_execute(
            f"SELECT person_id FROM {table} WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND person_id IN %(person_uuids)s GROUP BY person_id",
            {
                "team_id": team_id,
                "cohort_id": self.pk,
                "person_uuids": person_uuids,
            },
        )
        return {str(row[0]) for row in rows}

    def remove_user_by_uuid(self, user_uuid: str, *, team_id: int) -> bool:
        """
        Remove a user from the cohort by their UUID.

        This operation is idempotent - it succeeds even if the person wasn't in the cohort,
        to handle cases where ClickHouse and PostgreSQL data may be out of sync.

        Args:
            user_uuid: UUID of the user to be removed from the cohort.
            team_id: ID of the team to which the cohort belongs
        Returns:
            True if the person exists (removal attempted), False if the person doesn't exist.
        Raises:
            Exception: If removal fails due to database errors.
        """
        from products.cohorts.backend.models.util import (
            delete_cohort_member,
            get_static_cohort_size,
            is_person_in_cohort,
            remove_person_from_static_cohort,
        )

        try:
            # Only person.id/uuid are used (to resolve and remove the row), so skip the distinct-id fetch.
            with personhog_caller_tag("cohorts/static-remove"):
                person = get_person_by_uuid(team_id, str(user_uuid), distinct_id_limit=0)
            if person is None:
                raise Person.DoesNotExist

            # Check if person is in the cohort via personhog.
            is_member = is_person_in_cohort(team_id=team_id, person_id=person.id, cohort_id=self.id)

            # Delete from PostgreSQL first (source of truth), then ClickHouse.
            # This order ensures if PG delete fails, we don't create inverse inconsistency.
            if is_member:
                delete_cohort_member(team_id=team_id, cohort_id=self.id, person_id=person.id)
            else:
                # Person not in PG - this is expected when handling CH/PG sync issues
                logger.info(
                    "Removing person from cohort: not in PostgreSQL CohortPeople table",
                    cohort_id=self.id,
                    team_id=team_id,
                    user_uuid=user_uuid,
                )

            # Always attempt CH delete - it's idempotent and handles cases where
            # data exists in CH but not PG due to past sync issues
            remove_person_from_static_cohort(person.uuid, self.pk, team_id=team_id)

            try:
                count = get_static_cohort_size(
                    cohort_id=self.id,
                    team_id=team_id,
                    consistency="strong",
                )
                self.count = count
                self.save(update_fields=["count"])
            except Exception as count_err:
                logger.exception(
                    "Failed to update cohort count after removal",
                    cohort_id=self.id,
                    team_id=team_id,
                )
                capture_exception(
                    count_err,
                    additional_properties={"cohort_id": self.id, "team_id": team_id},
                )

            return True

        except Person.DoesNotExist:
            return False
        except Exception as err:
            logger.exception(
                "Failed to remove user from cohort",
                cohort_id=self.id,
                team_id=team_id,
                user_uuid=user_uuid,
            )
            capture_exception(
                err,
                additional_properties={
                    "cohort_id": self.id,
                    "team_id": team_id,
                    "user_uuid": user_uuid,
                },
            )
            raise

    def to_dict(self) -> dict:
        from posthog.models.activity_logging.activity_log import common_field_exclusions, field_exclusions

        excluded_fields = field_exclusions.get("Cohort", []) + common_field_exclusions
        base_dict = {
            "id": self.pk,
            "name": self.name,
            "description": self.description,
            "team_id": self.team_id,
            "deleted": self.deleted,
            "filters": self.filters,
            "query": self.query,
            "groups": self.groups,
            "is_static": self.is_static,
            "cohort_type": self.cohort_type,
            "created_by_id": self.created_by_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
        }
        return {k: v for k, v in base_dict.items() if k not in excluded_fields}

    def _safe_save_cohort_state(self, *, team_id: int, processing_error=None) -> None:
        """
        Save only the cohort's calculation-state fields with a single retry on failure.

        Only updates `is_calculating`, `count`, and either success fields
        (`last_calculation`, `errors_calculating`) or error fields
        (`errors_calculating`, `last_error_at`) — never the full model — so
        concurrent edits to other cohort fields are not overwritten.

        Args:
            team_id: Team ID for logging context
            processing_error: Error from processing, if any. Used to update error state.
        """
        self.is_calculating = False

        if processing_error is None:
            self.last_calculation = timezone.now()
            self.errors_calculating = 0
            save_fields = ["is_calculating", "last_calculation", "errors_calculating", "count"]
        else:
            self.errors_calculating = F("errors_calculating") + 1
            self.last_error_at = timezone.now()
            save_fields = ["is_calculating", "errors_calculating", "last_error_at", "count"]
        try:
            self.save(update_fields=save_fields)
        except Exception as save_err:
            logger.exception("Failed to save cohort state", cohort_id=self.id, team_id=team_id)
            capture_exception(
                save_err,
                additional_properties={"cohort_id": self.id, "team_id": team_id},
            )

            # Single retry for transient issues
            try:
                self.save(update_fields=save_fields)
            except Exception:
                logger.exception(
                    "Failed to save cohort state on retry",
                    cohort_id=self.id,
                    team_id=team_id,
                )
                # If both attempts fail, the cohort may remain in an inconsistent state

    def enqueue_calculation(self, *, initiating_user=None) -> None:
        """
        Enqueue this cohort to be recalculated.

        Args:
            initiating_user (User): The user who initiated the calculation.
        """

        def trigger_calculation():
            from posthog.tasks.calculate_cohort import increment_version_and_enqueue_calculate_cohort

            increment_version_and_enqueue_calculate_cohort(self, initiating_user=initiating_user)

        transaction.on_commit(trigger_calculation)

    __repr__ = sane_repr("id", "name", "last_calculation")


INTERNAL_TEST_USERS_COHORT_NAME = "Internal / Test users"


def get_or_create_internal_test_users_cohort(
    team: "Team",
    initiating_user_email: str | None = None,
) -> "Cohort":
    """
    Get or create an 'Internal / Test users' cohort for the team.

    Contains users with $internal_or_test_user set to true, and optionally
    users whose email matches the creating user's domain (if not a generic provider).
    """
    from posthog.utils import GenericEmails

    existing = Cohort.objects.filter(team=team, kind=CohortKind.INTERNAL_TEST_USERS).first()
    if existing is not None:
        return existing

    # Always include the $internal_or_test_user property filter
    filter_groups: list[dict] = [
        {
            "type": "AND",
            "values": [
                {
                    "key": "$internal_or_test_user",
                    "type": "person",
                    "value": [True],
                    "operator": "exact",
                }
            ],
        }
    ]

    # Add email domain filter if the creating user has a non-generic domain
    if initiating_user_email:
        generic_emails = GenericEmails()
        if not generic_emails.is_generic(initiating_user_email):
            match = re.search(r"@([\w.]+)", initiating_user_email)
            if match:
                domain = match.group(1).lower()
                filter_groups.append(
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": f"@{domain}",
                                "operator": "icontains",
                            }
                        ],
                    }
                )

    return Cohort.objects.create(
        team=team,
        name=INTERNAL_TEST_USERS_COHORT_NAME,
        description="People who are internal team members or test users. Used for filtering out internal traffic from analytics.",
        is_static=False,
        kind=CohortKind.INTERNAL_TEST_USERS,
        filters={
            "properties": {
                "type": "OR",
                "values": filter_groups,
            }
        },
    )


class CohortPeople(models.Model):
    id = models.BigAutoField(primary_key=True)
    cohort = models.ForeignKey("Cohort", on_delete=models.DO_NOTHING, db_constraint=False)
    person = models.ForeignKey("posthog.Person", on_delete=models.DO_NOTHING, db_constraint=False)
    version = models.IntegerField(blank=True, null=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        indexes = [models.Index(fields=["cohort_id", "person_id"])]
        db_table = "posthog_cohortpeople"


@receiver(post_delete, sender=CohortPeople)
def cohort_people_changed(sender, instance: "CohortPeople", **kwargs):
    from products.cohorts.backend.models.util import get_static_cohort_size

    try:
        cohort_id = instance.cohort_id
        person_uuid = instance.person_id

        cohort = Cohort.objects.get(id=cohort_id)
        cohort.count = get_static_cohort_size(
            cohort_id=cohort.id,
            team_id=cohort.team_id,
            consistency="strong",
        )

        # Clear cohort_type if count exceeds the realtime threshold
        if cohort.cohort_type == CohortType.REALTIME and cohort.count > REALTIME_COHORT_MAX_PERSON_COUNT:
            cohort.cohort_type = None
            cohort.save(update_fields=["count", "cohort_type"])
            logger.info(
                "Cleared cohort_type for cohort exceeding realtime threshold",
                cohort_id=cohort_id,
                count=cohort.count,
                threshold=REALTIME_COHORT_MAX_PERSON_COUNT,
            )
        else:
            cohort.save(update_fields=["count"])

        logger.info(
            "Updated cohort count after CohortPeople change",
            cohort_id=cohort_id,
            person_uuid=person_uuid,
            new_count=cohort.count,
        )
    except Cohort.DoesNotExist:
        logger.warning("Attempted to update count for non-existent cohort", cohort_id=cohort_id)
    except Exception as e:
        logger.exception("Error updating cohort count", cohort_id=cohort_id, person_uuid=person_uuid)
        capture_exception(e)
