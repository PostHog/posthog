import time
from datetime import datetime
from typing import Any, Literal, Optional, Union, cast, TYPE_CHECKING

import posthoganalytics
import structlog
from django.conf import settings
from django.db import connection, models
from django.db.models import Q, QuerySet
from django.db.models.expressions import F

from django.utils import timezone
from posthog.exceptions_capture import capture_exception

from posthog.constants import PropertyOperatorType
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.models.person.person import READ_DB_FOR_PERSONS
from posthog.models.property import BehavioralPropertyType, Property, PropertyGroup
from posthog.models.utils import RootTeamManager, RootTeamMixin, sane_repr
from posthog.settings.base_variables import TEST
from posthog.models.file_system.file_system_representation import FileSystemRepresentation

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
            base_folder=self._create_in_folder or "Unfiled/Cohorts",
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

    def get_analytics_metadata(self):
        return {
            "filters": self.properties.to_dict(),
            "name_length": len(self.name) if self.name else 0,
            "deleted": self.deleted,
        }

    def calculate_people_ch(self, pending_version: int, *, initiating_user_id: Optional[int] = None):
        from posthog.models.cohort.util import recalculate_cohortpeople

        use_hogql_cohorts = posthoganalytics.feature_enabled(
            "enable_hogql_cohort_calculation",
            str(self.team.organization_id),
            groups={"organization": str(self.team.organization_id)},
            group_properties={"organization": {"id": str(self.team.organization_id)}},
        )

        logger.warn(
            "cohort_calculation_started",
            id=self.pk,
            current_version=self.version,
            new_version=pending_version,
        )
        start_time = time.monotonic()

        try:
            count = recalculate_cohortpeople(
                self, pending_version, initiating_user_id=initiating_user_id, hogql=use_hogql_cohorts
            )
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

    def insert_users_by_list(self, items: list[str], *, team_id: Optional[int] = None) -> None:
        """
        Insert a list of users identified by their distinct ID into the cohort, for the given team.

        Args:
            items: List of distinct IDs of users to be inserted into the cohort.
            team_id: ID of the team for which to insert the users. Defaults to `self.team`, because of a lot of existing usage in tests.
        """
        if team_id is None:
            team_id = self.team_id
        batchsize = 1000
        from posthog.models.cohort.util import (
            insert_static_cohort,
            get_static_cohort_size,
        )

        if TEST:
            from posthog.test.base import flush_persons_and_events

            # Make sure persons are created in tests before running this
            flush_persons_and_events()

        try:
            cursor = connection.cursor()
            for i in range(0, len(items), batchsize):
                batch = items[i : i + batchsize]
                persons_query = (
                    Person.objects.db_manager(READ_DB_FOR_PERSONS)
                    .filter(team_id=team_id)
                    .filter(
                        Q(
                            persondistinctid__team_id=team_id,
                            persondistinctid__distinct_id__in=batch,
                        )
                    )
                    .exclude(cohort__id=self.id)
                )
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
        except Exception as err:
            if settings.DEBUG:
                raise
            self.is_calculating = False
            self.errors_calculating = F("errors_calculating") + 1
            self.last_error_at = timezone.now()
            self.save()
            capture_exception(err)

    def insert_users_list_by_uuid(
        self, items: list[str], insert_in_clickhouse: bool = False, batchsize=1000, *, team_id: int
    ) -> None:
        """
        Insert a list of users identified by their UUID into the cohort, for the given team.

        Args:
            items: List of user UUIDs to be inserted into the cohort.
            insert_in_clickhouse: Whether the data should also be inserted into ClickHouse.
            batchsize: Number of UUIDs to process in each batch.
            team_id: The ID of the team to which the cohort belongs.
        """
        from posthog.models.cohort.util import get_static_cohort_size, insert_static_cohort

        try:
            cursor = connection.cursor()
            for i in range(0, len(items), batchsize):
                batch = items[i : i + batchsize]
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
        except Exception as err:
            if settings.DEBUG:
                raise
            self.is_calculating = False
            self.errors_calculating = F("errors_calculating") + 1
            self.last_error_at = timezone.now()

            self.save()
            capture_exception(err)

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
