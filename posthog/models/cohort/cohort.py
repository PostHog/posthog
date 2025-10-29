import time
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Optional, Union, cast

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q, QuerySet
from django.db.models.expressions import F
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

import structlog

from posthog.constants import PropertyOperatorType
from posthog.exceptions_capture import capture_exception
from posthog.helpers.batch_iterators import ArrayBatchIterator, BatchIterator, FunctionBatchIterator
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.filters.filter import Filter
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.person import READ_DB_FOR_PERSONS
from posthog.models.property import Property, PropertyGroup
from posthog.models.utils import RootTeamManager, RootTeamMixin, sane_repr
from posthog.settings.base_variables import TEST

if TYPE_CHECKING:
    from posthog.models.team import Team


class CohortType(StrEnum):
    STATIC = "static"
    PERSON_PROPERTY = "person_property"
    BEHAVIORAL = "behavioral"
    REALTIME = "realtime"
    ANALYTICAL = "analytical"


# The empty string literal helps us determine when the cohort is invalid/deleted, when
# set in cohorts_cache
CohortOrEmpty = Union["Cohort", Literal[""], None]

logger = structlog.get_logger(__name__)

DELETE_QUERY = """
DELETE FROM "posthog_cohortpeople" WHERE "cohort_id" = {cohort_id}
"""

UPDATE_QUERY = """
INSERT INTO "posthog_cohortpeople" ("person_id", "cohort_id", "version")
{values_query}
ON CONFLICT DO NOTHING
"""

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


class Cohort(FileSystemSyncMixin, RootTeamMixin, models.Model):
    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.CharField(max_length=1000, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    deleted = models.BooleanField(default=False)
    filters = models.JSONField(
        null=True,
        blank=True,
        help_text="""Filters for the cohort. Examples:

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

        # Cohort filter
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
    people = models.ManyToManyField("Person", through="CohortPeople")
    version = models.IntegerField(blank=True, null=True)
    pending_version = models.IntegerField(blank=True, null=True)
    count = models.IntegerField(blank=True, null=True)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, blank=True, null=True)

    is_calculating = models.BooleanField(default=False)
    last_calculation = models.DateTimeField(blank=True, null=True)
    errors_calculating = models.IntegerField(default=0)
    last_error_at = models.DateTimeField(blank=True, null=True)

    is_static = models.BooleanField(default=False)

    cohort_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=[(cohort_type.value, cohort_type.value) for cohort_type in CohortType],
        help_text="Type of cohort based on filter complexity",
    )

    # Compiled bytecode for realtime evaluation
    compiled_bytecode = models.JSONField(
        null=True,
        blank=True,
        help_text="Array of compiled bytecode objects for filters that support realtime evaluation.",
    )

    # deprecated in favor of filters
    groups = models.JSONField(default=list)

    objects = CohortManager()  # type: ignore

    def __str__(self):
        return self.name or "Untitled cohort"

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["Cohort"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="cohort", ref_field="id")

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

    def calculate_people_ch(self, pending_version: int, *, initiating_user_id: Optional[int] = None):
        from posthog.models.cohort.util import recalculate_cohortpeople

        logger.warn(
            "cohort_calculation_started",
            id=self.pk,
            current_version=self.version,
            new_version=pending_version,
        )
        start_time = time.monotonic()

        try:
            count = recalculate_cohortpeople(self, pending_version, initiating_user_id=initiating_user_id)
            self.count = count

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
            self.is_calculating = False
            self.save()

        # Update filter to match pending version if still valid
        Cohort.objects.filter(pk=self.pk).filter(Q(version__lt=pending_version) | Q(version__isnull=True)).update(
            version=pending_version, count=count
        )
        self.refresh_from_db()

        logger.warn(
            "cohort_calculation_completed",
            id=self.pk,
            version=pending_version,
            duration=(time.monotonic() - start_time),
        )

    def _get_uuids_for_distinct_ids_batch(self, distinct_ids: list[str], team_id: int) -> list[str]:
        """
        Get UUIDs for a batch of distinct IDs, excluding those already in this cohort.

        Args:
            distinct_ids: List of distinct IDs to convert to UUIDs
            team_id: Team ID to filter by

        Remarks:
            This used to be a single query with a complex JOIN, but that query was timing out.
            So we split it into two queries that are much simpler and should hopefully not time out.

        Returns:
            List of UUIDs for persons with the given distinct IDs who are not already in this cohort
        """
        if not distinct_ids:
            return []

        # Get person_ids for this batch of distinct IDs
        # This is limited to the batch size so it will be no more than 1000 items in-memory at a time.
        person_ids_qs = (
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=team_id, distinct_id__in=distinct_ids)
            .values_list("person_id", flat=True)
            .distinct()
        )

        # Grab uuids for this batch of distinct IDs
        # You're going to be tempted to exclude people already in the cohort, but that's not only NOT
        # necessary, but it leads to query timeouts. The insert_users_list_by_uuid handles ensuring we
        # don't insert people that are already in the cohort efficiently.
        uuids = [
            str(uuid)
            for uuid in Person.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=team_id, id__in=person_ids_qs)
            .values_list("uuid", flat=True)
        ]

        return uuids

    def insert_users_by_list(
        self, items: list[str], *, team_id: Optional[int] = None, batch_size: int = DEFAULT_COHORT_INSERT_BATCH_SIZE
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

        # Process distinct IDs in batches to avoid memory issues
        def create_uuid_batch(batch_index: int, batch_size: int) -> list[str]:
            """Create a batch of UUIDs from distinct IDs, excluding those already in cohort."""
            start_idx = batch_index * batch_size
            end_idx = start_idx + batch_size
            batch_distinct_ids = items[start_idx:end_idx]

            return self._get_uuids_for_distinct_ids_batch(batch_distinct_ids, team_id)

        # Use FunctionBatchIterator to process distinct IDs in batches
        batch_iterator = FunctionBatchIterator(create_uuid_batch, batch_size=batch_size, max_items=len(items))

        # Call the batching method with ClickHouse insertion enabled
        return self._insert_users_list_with_batching(batch_iterator, insert_in_clickhouse=True, team_id=team_id)

    def insert_users_list_by_uuid(
        self,
        items: list[str],
        batchsize=DEFAULT_COHORT_INSERT_BATCH_SIZE,
        *,
        team_id: int,
    ) -> int:
        """
        Insert a list of users identified by their UUID into the cohort, for the given team.

        Args:
            items: List of user UUIDs to be inserted into the cohort.
            batchsize: Number of UUIDs to process in each batch.
            team_id: The ID of the team to which the cohort belongs.

        Returns:
            The number of batches processed.
        """

        batch_iterator = ArrayBatchIterator(items, batch_size=batchsize)
        return self._insert_users_list_with_batching(batch_iterator, insert_in_clickhouse=True, team_id=team_id)

    def insert_users_by_email(
        self, items: list[str], *, team_id: Optional[int] = None, batch_size: int = DEFAULT_COHORT_INSERT_BATCH_SIZE
    ) -> int:
        """
        Insert a list of users identified by their email address into the cohort, for the given team.
        Args:
            items: List of email addresses of users to be inserted into the cohort.
            team_id: ID of the team for which to insert the users. Defaults to `self.team`, because of a lot of existing usage in tests.
            batch_size: Number of records to process in each batch. Defaults to 1000.
        """
        if team_id is None:
            team_id = self.team_id

        if TEST:
            from posthog.test.base import flush_persons_and_events

            # Make sure persons are created in tests before running this
            flush_persons_and_events()

        # Process emails in batches to avoid memory issues
        def create_uuid_batch(batch_index: int, batch_size: int) -> list[str]:
            """Create a batch of UUIDs from email addresses, excluding those already in cohort."""
            start_idx = batch_index * batch_size
            end_idx = start_idx + batch_size
            batch_emails = items[start_idx:end_idx]
            uuids = self._get_uuids_for_emails_batch(batch_emails, team_id)
            return uuids

        # Use FunctionBatchIterator to process emails in batches
        batch_iterator = FunctionBatchIterator(create_uuid_batch, batch_size=batch_size, max_items=len(items))

        # Call the batching method with ClickHouse insertion enabled
        return self._insert_users_list_with_batching(batch_iterator, insert_in_clickhouse=True, team_id=team_id)

    def _get_uuids_for_emails_batch(self, emails: list[str], team_id: int) -> list[str]:
        """
        Get UUIDs for a batch of email addresses, excluding those already in this cohort.

        Args:
            emails: List of email addresses to convert to UUIDs
            team_id: Team ID to filter by

        Returns:
            List of UUIDs for persons with the given email addresses who are not already in this cohort
        """
        if not emails:
            return []

        uuids = [
            str(uuid)
            for uuid in Person.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=team_id)
            .filter(properties__email__in=emails)
            .values_list("uuid", flat=True)
        ]

        return uuids

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
        self, batch_iterator: BatchIterator[str], insert_in_clickhouse: bool = False, *, team_id: int
    ) -> int:
        """
        Insert a list of users identified by their UUID into the cohort, for the given team.

        Args:
            batch_iterator: BatchIterator of user UUIDs to be inserted into the cohort.
            insert_in_clickhouse: Whether the data should also be inserted into ClickHouse.
            batchsize: Number of UUIDs to process in each batch.
            team_id: The ID of the team to which the cohort belongs.

        Returns:
            Number of batches processed.
        """
        from posthog.models.cohort.util import get_static_cohort_size, insert_static_cohort

        current_batch_index = -1
        processing_error = None
        try:
            from django.db import connections

            persons_connection = connections[READ_DB_FOR_PERSONS]
            cursor = persons_connection.cursor()
            for batch_index, batch in batch_iterator:
                current_batch_index = batch_index
                persons_query = (
                    Person.objects.db_manager(READ_DB_FOR_PERSONS)
                    .filter(team_id=team_id)
                    .filter(uuid__in=batch)
                    .exclude(cohort__id=self.id)
                )
                if insert_in_clickhouse:
                    insert_static_cohort(
                        list(persons_query.values_list("uuid", flat=True)),
                        self.pk,
                        team_id=team_id,
                    )
                sql, params = persons_query.distinct("pk").only("pk").query.sql_with_params()
                query = UPDATE_QUERY.format(
                    cohort_id=self.pk,
                    values_query=sql.replace(
                        'FROM "posthog_person"',
                        f', {self.pk}, {self.version or "NULL"} FROM "posthog_person"',
                        1,
                    ),
                )
                cursor.execute(query, params)

        except Exception as err:
            processing_error = err
            if settings.DEBUG:
                raise
            # Add batch index context to the exception
            capture_exception(
                err,
                additional_properties={"cohort_id": self.id, "team_id": team_id, "batch_index": current_batch_index},
            )
        finally:
            # Always update the count and cohort state, even if processing failed
            try:
                count = get_static_cohort_size(cohort_id=self.id, team_id=self.team_id)
                self.count = count
            except Exception as count_err:
                # If count calculation fails, log the error but don't override the processing error
                logger.exception("Failed to calculate static cohort size", cohort_id=self.id, team_id=team_id)
                capture_exception(count_err, additional_properties={"cohort_id": self.id, "team_id": team_id})
                # Leave existing count unchanged - it's better than None

            self._safe_save_cohort_state(team_id=team_id, processing_error=processing_error)

        return current_batch_index + 1

    def remove_user_by_uuid(self, user_uuid: str, *, team_id: int) -> bool:
        """
        Remove a user from the cohort by their UUID.

        Args:
            user_uuid: UUID of the user to be removed from the cohort.
            team_id: ID of the team to which the cohort belongs
        Returns:
            True if user was removed, False if user was not in the cohort.
        """
        from posthog.models.cohort.util import get_static_cohort_size, remove_person_from_static_cohort

        try:
            # Get person by UUID
            person = Person.objects.db_manager(READ_DB_FOR_PERSONS).get(team_id=team_id, uuid=user_uuid)

            # Check if person is in the cohort
            cohort_person = CohortPeople.objects.filter(
                cohort_id=self.id,
                person_id=person.id,
            ).first()

            if not cohort_person:
                return False

            # Remove from both PostgreSQL and ClickHouse
            cohort_person.delete()
            remove_person_from_static_cohort(person.uuid, self.pk, team_id=team_id)

            # Update count
            try:
                count = get_static_cohort_size(cohort_id=self.id, team_id=team_id)
                self.count = count
                self.save(update_fields=["count"])
            except Exception as count_err:
                logger.exception("Failed to update cohort count after removal", cohort_id=self.id, team_id=team_id)
                capture_exception(count_err, additional_properties={"cohort_id": self.id, "team_id": team_id})

            return True

        except Person.DoesNotExist:
            return False
        except Exception as err:
            logger.exception(
                "Failed to remove user from cohort", cohort_id=self.id, team_id=team_id, user_uuid=user_uuid
            )
            capture_exception(
                err, additional_properties={"cohort_id": self.id, "team_id": team_id, "user_uuid": user_uuid}
            )
            raise

    def to_dict(self) -> dict:
        people_data = [
            {
                "id": person.id,
                "email": person.email or "(no email)",
                "distinct_id": person.distinct_ids[0] if person.distinct_ids else "(no distinct id)",
            }
            for person in self.people.all()
        ]

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
            "people": people_data,
        }
        return {k: v for k, v in base_dict.items() if k not in excluded_fields}

    def _safe_save_cohort_state(self, *, team_id: int, processing_error=None) -> None:
        """
        Safely save cohort state with fallback to save only critical fields.

        This prevents cohorts from getting stuck in calculating state when
        database issues occur during cleanup operations.

        Args:
            team_id: Team ID for logging context
            processing_error: Error from processing, if any. Used to update error state.
        """
        self.is_calculating = False

        if processing_error is None:
            self.last_calculation = timezone.now()
            self.errors_calculating = 0
        else:
            self.errors_calculating = F("errors_calculating") + 1
            self.last_error_at = timezone.now()
        try:
            self.save()
        except Exception as save_err:
            logger.exception("Failed to save cohort state", cohort_id=self.id, team_id=team_id)
            capture_exception(save_err, additional_properties={"cohort_id": self.id, "team_id": team_id})

            # Single retry for transient issues
            try:
                self.save()
            except Exception:
                logger.exception("Failed to save cohort state on retry", cohort_id=self.id, team_id=team_id)
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


class CohortPeople(models.Model):
    id = models.BigAutoField(primary_key=True)
    cohort = models.ForeignKey("Cohort", on_delete=models.CASCADE)
    person = models.ForeignKey("Person", on_delete=models.CASCADE)
    version = models.IntegerField(blank=True, null=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        indexes = [models.Index(fields=["cohort_id", "person_id"])]


@receiver(post_delete, sender=CohortPeople)
def cohort_people_changed(sender, instance: "CohortPeople", **kwargs):
    from posthog.models.cohort.util import get_static_cohort_size

    try:
        cohort_id = instance.cohort_id
        person_uuid = instance.person_id

        cohort = Cohort.objects.get(id=cohort_id)
        cohort.count = get_static_cohort_size(cohort_id=cohort.id, team_id=cohort.team_id)
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
