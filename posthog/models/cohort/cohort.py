import time
from datetime import datetime
from typing import Any, Literal, Optional, Union, cast, TYPE_CHECKING

import structlog
from django.conf import settings
from django.db import connection, models
from django.db.models import Q, QuerySet
from django.db.models.expressions import F

from django.utils import timezone
from posthog.exceptions_capture import capture_exception

from posthog.constants import PropertyOperatorType
from posthog.helpers.batch_iterators import ArrayBatchIterator, BatchIterator, FunctionBatchIterator
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.models.person.person import READ_DB_FOR_PERSONS
from posthog.models.property import BehavioralPropertyType, Property, PropertyGroup
from posthog.models.utils import RootTeamManager, RootTeamMixin, sane_repr
from posthog.settings.base_variables import TEST
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.person import PersonDistinctId

if TYPE_CHECKING:
    from posthog.models.team import Team


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


class CohortType(models.TextChoices):
    STATIC = "static", "Static"
    PERSON_PROPERTY = "person_property", "Person Property"
    BEHAVIORAL = "behavioral", "Behavioral"
    ANALYTICAL = "analytical", "Analytical"


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

    # deprecated in favor of filters
    groups = models.JSONField(default=list)

    cohort_type = models.CharField(
        max_length=20,
        choices=CohortType.choices,
        null=True,
        blank=True,
        help_text="The type of cohort, determines where in the app it can be used.  It is automatically set based on the filters, and can't be set via the API or UI.",
    )

    objects = CohortManager()  # type: ignore

    def __str__(self):
        return self.name or "Untitled cohort"

    def save(self, *args, **kwargs):
        """
        Override save to automatically update cohort type.
        """
        # Always validate and update cohort type
        self._validate_cohort_classification()
        self.update_cohort_type()

        # Log the cohort type assignment for debugging
        logger.info(
            "cohort_type_assigned",
            cohort_id=self.pk,
            cohort_type=self.cohort_type,
            team_id=self.team_id if self.team_id else None,
        )

        super().save(*args, **kwargs)

        # After saving, update any cohorts that depend on this one
        # This ensures cascade updates when a cohort's type changes
        self._update_dependent_cohort_types()

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

    @property
    def has_complex_behavioral_filter(self) -> bool:
        for prop in self.properties.flat:
            if prop.type == "behavioral" and prop.value in [
                BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                BehavioralPropertyType.PERFORMED_EVENT_REGULARLY,
                BehavioralPropertyType.PERFORMED_EVENT_SEQUENCE,
                BehavioralPropertyType.STOPPED_PERFORMING_EVENT,
                BehavioralPropertyType.RESTARTED_PERFORMING_EVENT,
            ]:
                return True
        return False

    def _get_direct_cohort_type(self) -> CohortType:
        """
        Determine cohort type based on this cohort's direct filters only (ignoring dependencies).
        Fails explicitly if type cannot be determined.
        """
        # Static cohorts have no properties/filters
        if self.is_static:
            return CohortType.STATIC

        # No filters means static
        if not self.properties.flat:
            return CohortType.STATIC

        has_person_props = False
        has_behavioral_props = False
        has_complex_behavioral = False
        has_unknown_props = False

        for prop in self.properties.flat:
            if prop.type == "person":
                has_person_props = True
            elif prop.type == "behavioral":
                has_behavioral_props = True
                if prop.value in [
                    BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                    BehavioralPropertyType.PERFORMED_EVENT_REGULARLY,
                    BehavioralPropertyType.PERFORMED_EVENT_SEQUENCE,
                    BehavioralPropertyType.STOPPED_PERFORMING_EVENT,
                    BehavioralPropertyType.RESTARTED_PERFORMING_EVENT,
                ]:
                    has_complex_behavioral = True
            elif prop.type == "cohort":
                # Cohort dependencies don't affect direct type
                pass
            else:
                # Unknown property type
                has_unknown_props = True

        # Fail if we encounter unknown property types
        if has_unknown_props:
            unknown_types = [
                prop.type for prop in self.properties.flat if prop.type not in ["person", "behavioral", "cohort"]
            ]
            raise ValueError(f"Cannot determine cohort type: unknown property types {set(unknown_types)}")

        # Determine type based on most complex filter present
        if has_complex_behavioral:
            return CohortType.ANALYTICAL
        elif has_behavioral_props:
            return CohortType.BEHAVIORAL
        elif has_person_props:
            return CohortType.PERSON_PROPERTY
        else:
            return CohortType.STATIC

    def _get_dependent_cohort_ids(self) -> set[int]:
        """
        Get IDs of all cohorts this cohort depends on.
        """
        dependent_ids = set()
        for prop in self.properties.flat:
            if prop.type == "cohort" and prop.value is not None and not isinstance(prop.value, list):
                try:
                    cohort_id = int(prop.value)
                    dependent_ids.add(cohort_id)
                except (ValueError, TypeError):
                    pass
        return dependent_ids

    def _get_all_transitive_dependency_ids(self) -> set[int]:
        """
        Get all cohort IDs this cohort transitively depends on using BFS with batch fetching.
        Returns the complete set of dependency IDs efficiently.
        """
        all_dependencies = set()
        to_process = set(self._get_dependent_cohort_ids())
        visited = set()

        while to_process:
            # Batch fetch all cohorts we need to process in this iteration
            current_batch = to_process.copy()
            to_process.clear()

            # Check for circular dependencies
            if self.pk in current_batch:
                raise ValueError(f"Circular dependency detected in cohort {self.pk}")

            # Batch fetch all cohorts in current batch
            current_cohorts = {
                c.pk: c for c in Cohort.objects.filter(pk__in=current_batch, team=self.team, deleted=False)
            }

            for cohort_id in current_batch:
                if cohort_id in visited:
                    continue

                visited.add(cohort_id)
                all_dependencies.add(cohort_id)

                # Get dependencies from fetched cohort
                if cohort_id in current_cohorts:
                    cohort = current_cohorts[cohort_id]
                    new_dependencies = cohort._get_dependent_cohort_ids()
                    to_process.update(new_dependencies - visited)

        return all_dependencies

    def _calculate_cohort_type_with_dependencies(self, visited: Optional[set[int]] = None) -> CohortType:
        """
        Calculate cohort type considering dependencies using batch fetching.
        Much more efficient than recursive approach - fetches all needed cohorts in one query.
        """
        if visited is None:
            visited = set()

        # Prevent infinite loops in case of circular dependencies
        if self.pk and self.pk in visited:
            raise ValueError(f"Circular dependency detected in cohort {self.pk}")

        # Get all transitive dependencies in one go
        all_dependency_ids = self._get_all_transitive_dependency_ids()

        # Batch fetch all dependent cohorts
        cohorts_map = {c.pk: c for c in Cohort.objects.filter(pk__in=all_dependency_ids, team=self.team, deleted=False)}

        # Check if any dependencies are missing
        missing_ids = all_dependency_ids - set(cohorts_map.keys())
        if missing_ids:
            raise ValueError(f"Referenced cohorts do not exist: {missing_ids}")

        # Now calculate type in-memory
        return self._calculate_type_from_cohort_map(cohorts_map, visited)

    def _calculate_type_from_cohort_map(self, cohorts_map: dict[int, "Cohort"], visited: set[int]) -> CohortType:
        """
        Calculate cohort type using pre-fetched cohort map. Avoids additional DB queries.
        """
        if self.pk and self.pk in visited:
            raise ValueError(f"Circular dependency detected in cohort {self.pk}")

        if self.pk:
            visited.add(self.pk)

        # Start with this cohort's direct type
        current_type = self._get_direct_cohort_type()

        # Type complexity order for comparison
        type_order = {
            CohortType.STATIC: 0,
            CohortType.PERSON_PROPERTY: 1,
            CohortType.BEHAVIORAL: 2,
            CohortType.ANALYTICAL: 3,
        }

        # Check all dependent cohorts and take the most complex type
        dependent_ids = self._get_dependent_cohort_ids()
        for cohort_id in dependent_ids:
            if cohort_id in cohorts_map:
                dependent_cohort = cohorts_map[cohort_id]
                dependent_type = dependent_cohort._calculate_type_from_cohort_map(cohorts_map, visited.copy())

                # Take the more complex type (higher order in the enum)
                if type_order[dependent_type] > type_order[current_type]:
                    current_type = dependent_type

        return current_type

    def determine_cohort_type(self) -> CohortType:
        """
        Public method to determine the cohort type, considering dependencies.
        """
        try:
            return self._calculate_cohort_type_with_dependencies()
        except ValueError as e:
            # Handle circular dependencies or other validation errors
            logger.exception("cohort_type_determination_failed", cohort_id=self.pk, error=str(e))
            raise

    def update_cohort_type(self) -> None:
        """
        Update the cohort_type field based on current filters and dependencies.
        """
        new_type = self.determine_cohort_type()
        if self.cohort_type != new_type:
            self.cohort_type = new_type

    def validate_for_feature_flags(self) -> None:
        """Validate that this cohort can be used in feature flags (no behavioral filters)"""
        from posthog.models.cohort.util import get_dependent_cohorts

        # Check direct behavioral filters
        for prop in self.properties.flat:
            if prop.type == "behavioral":
                from django.core.exceptions import ValidationError

                raise ValidationError("Behavioral filters cannot be added to cohorts used in feature flags.")

        # Check dependent cohorts for behavioral filters
        dependent_cohorts = get_dependent_cohorts(self)
        for dependent_cohort in dependent_cohorts:
            if any(p.type == "behavioral" for p in dependent_cohort.properties.flat):
                from django.core.exceptions import ValidationError

                raise ValidationError(
                    f"A dependent cohort ({dependent_cohort.name}) has filters based on events. These cohorts can't be used in feature flags."
                )

    def _validate_cohort_classification(self) -> None:
        """Validate that cohort type can be determined and dependencies exist."""
        try:
            # Check dependencies exist
            dependent_ids = self._get_dependent_cohort_ids()
            for cohort_id in dependent_ids:
                if not self.__class__.objects.filter(pk=cohort_id, team=self.team, deleted=False).exists():
                    from django.core.exceptions import ValidationError

                    raise ValidationError(f"Referenced cohort {cohort_id} does not exist or is deleted")

            # Validate cohort type can be determined (this also checks for circular deps)
            self.determine_cohort_type()

        except ValueError as e:
            from django.core.exceptions import ValidationError

            raise ValidationError(f"Invalid cohort configuration: {str(e)}")

    def clean(self) -> None:
        """
        Validate the cohort and determine its type.
        This method is called by full_clean() and form validation.
        """
        super().clean()
        self._validate_cohort_classification()

    def _update_dependent_cohort_types(self) -> None:
        """
        Update the types of all cohorts that depend on this one.
        This handles the case where changing this cohort's type affects dependent cohorts.
        """
        if not self.pk:
            return

        # Find all cohorts that reference this cohort
        dependent_cohorts = Cohort.objects.filter(
            team=self.team,
            deleted=False,
            filters__icontains=f'"value": {self.pk}',  # Simple string search for cohort references
        ).exclude(pk=self.pk)

        for dependent_cohort in dependent_cohorts:
            # Check if this cohort is actually referenced (more precise check)
            if self.pk in dependent_cohort._get_dependent_cohort_ids():
                try:
                    old_type = dependent_cohort.cohort_type
                    new_type = dependent_cohort.determine_cohort_type()
                    if old_type != new_type:
                        dependent_cohort.cohort_type = new_type
                        # Save without triggering cascade to avoid infinite recursion
                        dependent_cohort.save(update_fields=["cohort_type"])
                        logger.info(
                            "dependent_cohort_type_updated",
                            dependent_cohort_id=dependent_cohort.pk,
                            old_type=old_type,
                            new_type=new_type,
                            trigger_cohort_id=self.pk,
                        )
                except Exception as e:
                    logger.exception(
                        "dependent_cohort_type_update_failed",
                        dependent_cohort_id=dependent_cohort.pk,
                        trigger_cohort_id=self.pk,
                        error=str(e),
                    )

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
        insert_in_clickhouse: bool = False,
        batchsize=DEFAULT_COHORT_INSERT_BATCH_SIZE,
        *,
        team_id: int,
    ) -> None:
        """
        Insert a list of users identified by their UUID into the cohort, for the given team.

        Args:
            items: List of user UUIDs to be inserted into the cohort.
            insert_in_clickhouse: Whether the data should also be inserted into ClickHouse.
            batchsize: Number of UUIDs to process in each batch.
            team_id: The ID of the team to which the cohort belongs.
        """

        batch_iterator = ArrayBatchIterator(items, batch_size=batchsize)
        self._insert_users_list_with_batching(batch_iterator, insert_in_clickhouse, team_id=team_id)

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
        try:
            cursor = connection.cursor()
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

            count = get_static_cohort_size(cohort_id=self.id, team_id=self.team_id)
            self.count = count

            self.is_calculating = False
            self.last_calculation = timezone.now()
            self.errors_calculating = 0
            self.save()

            return current_batch_index + 1
        except Exception as err:
            if settings.DEBUG:
                raise
            self.is_calculating = False
            self.errors_calculating = F("errors_calculating") + 1
            self.last_error_at = timezone.now()

            self.save()
            # Add batch index context to the exception
            capture_exception(err, additional_properties={"batch_index": current_batch_index})

            return current_batch_index + 1

    def to_dict(self) -> dict:
        people_data = [
            {
                "id": person.id,
                "email": person.email or "(no email)",
                "distinct_id": person.distinct_ids[0] if person.distinct_ids else "(no distinct id)",
            }
            for person in self.people.all()
        ]

        from posthog.models.activity_logging.activity_log import field_exclusions, common_field_exclusions

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
            "created_by_id": self.created_by_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "people": people_data,
        }
        return {k: v for k, v in base_dict.items() if k not in excluded_fields}

    __repr__ = sane_repr("id", "name", "last_calculation")


class CohortPeople(models.Model):
    id = models.BigAutoField(primary_key=True)
    cohort = models.ForeignKey("Cohort", on_delete=models.CASCADE)
    person = models.ForeignKey("Person", on_delete=models.CASCADE)
    version = models.IntegerField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["cohort_id", "person_id"])]
