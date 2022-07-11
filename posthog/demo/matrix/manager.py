import datetime as dt
import json
from typing import Any, Dict, Literal, Optional, Tuple, cast

from django.conf import settings
from django.core import exceptions

from posthog.client import query_with_columns, sync_execute
from posthog.models import (
    Group,
    GroupTypeMapping,
    Organization,
    OrganizationMembership,
    Person,
    PersonDistinctId,
    Team,
    User,
)
from posthog.models.utils import UUIDT
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team

from .matrix import Matrix
from .models import SimPerson


class MatrixManager:
    # ID of the team under which demo data will be pre-saved
    MASTER_TEAM_ID = 0
    # Pre-save team
    MASTER_TEAM = Team(id=MASTER_TEAM_ID)

    matrix: Matrix
    pre_save: bool

    def __init__(self, matrix: Matrix, *, pre_save: bool):
        self.matrix = matrix
        self.pre_save = pre_save

    def ensure_account_and_save(
        self,
        email: str,
        first_name: str,
        organization_name: str,
        *,
        password: Optional[str] = None,
        disallow_collision: bool = False,
    ) -> Tuple[Organization, Team, User]:
        """If there's an email collision in signup in the demo environment, we treat it as a login."""
        existing_user: Optional[User] = User.objects.filter(email=email).first()
        if existing_user is None:
            organization_kwargs: Dict[str, Any] = {"name": organization_name}
            if settings.DEMO:
                organization_kwargs["plugins_access_level"] = Organization.PluginsAccessLevel.INSTALL
            organization = Organization.objects.create(**organization_kwargs)
            new_user = User.objects.create_and_join(
                organization, email, password, first_name, OrganizationMembership.Level.ADMIN
            )
            team = self.create_team(organization)
            self.run_on_team(team, new_user)
            return (organization, team, new_user)
        elif existing_user.is_staff:
            raise exceptions.PermissionDenied("Cannot log in as staff user without password.")
        elif disallow_collision:
            raise exceptions.ValidationError(
                f"Cannot save simulation data with email collision disallowed - there already is an account for {email}."
            )
        else:
            assert existing_user.organization is not None
            assert existing_user.team is not None
            return (existing_user.organization, existing_user.team, existing_user)

    @staticmethod
    def create_team(organization: Organization, **kwargs) -> Team:
        team = Team.objects.create(
            organization=organization, ingested_event=True, completed_snippet_onboarding=True, is_demo=True, **kwargs
        )
        return team

    def run_on_team(self, team: Team, user: User):
        if not self.pre_save or not self.is_demo_data_pre_saved():
            if self.matrix.simulation_complete is None:
                self.matrix.simulate()
            self.save_analytics_data(self.MASTER_TEAM if self.pre_save else team)
        if self.pre_save:
            self.copy_analytics_data_from_master_team(team)
        self.sync_postgres_with_clickhouse_data(team)
        self.matrix.set_project_up(team, user)
        calculate_event_property_usage_for_team(team.pk)
        team.save()

    def save_analytics_data(self, target_team: Team):
        if target_team.pk == self.MASTER_TEAM_ID:
            self.prepare_master_team()
        bulk_group_type_mappings = []
        for group_type_index, (group_type, groups) in enumerate(self.matrix.groups.items()):
            bulk_group_type_mappings.append(
                GroupTypeMapping(team=target_team, group_type_index=group_type_index, group_type=group_type)
            )
            for group_key, group in groups.items():
                self.save_sim_group(
                    target_team, cast(Literal[0, 1, 2, 3, 4], group_type_index), group_key, group, self.matrix.end
                )
        GroupTypeMapping.objects.bulk_create(bulk_group_type_mappings)
        sim_persons = self.matrix.people
        for sim_person in sim_persons:
            self.save_sim_person(target_team, sim_person)

    @classmethod
    def prepare_master_team(cls):
        if not Team.objects.filter(id=cls.MASTER_TEAM_ID).exists():
            organization = Organization.objects.create(name="PostHog")
            cls.create_team(organization, id=cls.MASTER_TEAM_ID, name="Master")

    @classmethod
    def copy_analytics_data_from_master_team(cls, target_team: Team):
        from posthog.models.event.sql import COPY_EVENTS_BETWEEN_TEAMS
        from posthog.models.group.sql import COPY_GROUPS_BETWEEN_TEAMS
        from posthog.models.person.sql import COPY_PERSON_DISTINCT_ID2S_BETWEEN_TEAMS, COPY_PERSONS_BETWEEN_TEAMS

        copy_params = {"source_team_id": cls.MASTER_TEAM_ID, "target_team_id": target_team.pk}
        sync_execute(COPY_PERSONS_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_PERSON_DISTINCT_ID2S_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_EVENTS_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_GROUPS_BETWEEN_TEAMS, copy_params)
        GroupTypeMapping.objects.bulk_create(
            (
                GroupTypeMapping(team=target_team, **record)
                for record in GroupTypeMapping.objects.filter(team=cls.MASTER_TEAM).values(
                    "group_type", "group_type_index", "name_singular", "name_plural"
                )
            )
        )

    @classmethod
    def sync_postgres_with_clickhouse_data(cls, target_team: Team):
        from posthog.models.group.sql import SELECT_GROUPS_OF_TEAM
        from posthog.models.person.sql import SELECT_PERSON_DISTINCT_ID2S_OF_TEAM, SELECT_PERSONS_OF_TEAM

        list_params = {"source_team_id": cls.MASTER_TEAM_ID}
        # Persons
        clickhouse_persons = query_with_columns(
            SELECT_PERSONS_OF_TEAM, list_params, ["team_id", "is_deleted", "_timestamp", "_offset"], {"id": "uuid"}
        )
        bulk_persons = []
        for row in clickhouse_persons:
            properties = json.loads(row.pop("properties", "{}"))
            bulk_persons.append(Person(team_id=target_team.pk, properties=properties, **row))
        Person.objects.bulk_create(bulk_persons)
        # Person distinct IDs
        clickhouse_distinct_ids = query_with_columns(
            SELECT_PERSON_DISTINCT_ID2S_OF_TEAM,
            list_params,
            ["team_id", "is_deleted", "_timestamp", "_offset", "_partition"],
            {"person_id": "person_uuid"},
        )
        bulk_person_distinct_ids = []
        for row in clickhouse_distinct_ids:
            person_uuid = row.pop("person_uuid")
            bulk_person_distinct_ids.append(
                PersonDistinctId(
                    team_id=target_team.pk, person=Person.objects.get(team_id=target_team.pk, uuid=person_uuid), **row
                )
            )
        PersonDistinctId.objects.bulk_create(bulk_person_distinct_ids)
        # Groups
        clickhouse_groups = query_with_columns(
            SELECT_GROUPS_OF_TEAM, list_params, ["team_id", "_timestamp", "_offset"],
        )
        bulk_groups = []
        for row in clickhouse_groups:
            properties = json.loads(row.pop("properties", "{}"))
            bulk_groups.append(Group(team_id=target_team.pk, version=0, **row))
        Group.objects.bulk_create(bulk_groups)

    @staticmethod
    def save_sim_person(team: Team, subject: SimPerson):
        if not subject.events:
            return  # Don't save a person who never participated
        from posthog.models.event.util import create_event
        from posthog.models.person.util import create_person, create_person_distinct_id

        person_uuid_str = str(UUIDT(unix_time_ms=int(subject.events[0].timestamp.timestamp() * 1000)))
        create_person(uuid=person_uuid_str, team_id=team.pk, properties=subject.properties, version=0)
        for distinct_id in subject.distinct_ids:
            create_person_distinct_id(team_id=team.pk, distinct_id=str(distinct_id), person_id=person_uuid_str)
        for event in subject.events:
            event_uuid = UUIDT(unix_time_ms=int(event.timestamp.timestamp() * 1000))
            create_event(
                event_uuid=event_uuid,
                event=event.event,
                team=team,
                distinct_id=event.properties["$distinct_id"],
                timestamp=event.timestamp,
                properties=event.properties,
            )

    @staticmethod
    def save_sim_group(
        team: Team, type_index: Literal[0, 1, 2, 3, 4], key: str, properties: Dict[str, Any], timestamp: dt.datetime
    ):
        from posthog.models.group.util import raw_create_group_ch

        raw_create_group_ch(team.pk, type_index, key, properties, timestamp)

    @classmethod
    def is_demo_data_pre_saved(cls) -> bool:
        from posthog.models.event.sql import GET_TOTAL_EVENTS_VOLUME

        total_events_volume = sync_execute(GET_TOTAL_EVENTS_VOLUME, {"team_id": cls.MASTER_TEAM_ID})[0][0]
        return total_events_volume > 0
