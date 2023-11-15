import datetime as dt
import json
from time import sleep
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

from django.conf import settings
from django.core import exceptions
from django.db import transaction, IntegrityError

from posthog.client import query_with_columns, sync_execute
from posthog.demo.matrix.taxonomy_inference import infer_taxonomy_for_team
from posthog.models import (
    Cohort,
    Group,
    GroupTypeMapping,
    Organization,
    OrganizationMembership,
    Person,
    PersonDistinctId,
    Team,
    User,
)
from posthog.models.async_deletion.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete_events import AsyncEventDeletion
from posthog.models.utils import UUIDT

from .matrix import Matrix
from .models import SimEvent, SimPerson


class MatrixManager:
    # ID of the team under which demo data will be pre-saved
    MASTER_TEAM_ID = 0

    matrix: Matrix
    use_pre_save: bool
    print_steps: bool

    _persons_created: int
    _person_distinct_ids_created: int

    def __init__(self, matrix: Matrix, *, use_pre_save: bool = False, print_steps: bool = False):
        self.matrix = matrix
        self.use_pre_save = use_pre_save
        self.print_steps = print_steps
        self._persons_created = 0
        self._person_distinct_ids_created = 0

    def ensure_account_and_save(
        self,
        email: str,
        first_name: str,
        organization_name: str,
        *,
        password: Optional[str] = None,
        is_staff: bool = False,
        disallow_collision: bool = False,
    ) -> Tuple[Organization, Team, User]:
        """If there's an email collision in signup in the demo environment, we treat it as a login."""
        existing_user: Optional[User] = User.objects.filter(email=email).first()
        if existing_user is None:
            if self.print_steps:
                print(f"Creating demo organization, project, and user...")
            organization_kwargs: Dict[str, Any] = {"name": organization_name}
            if settings.DEMO:
                organization_kwargs["plugins_access_level"] = Organization.PluginsAccessLevel.INSTALL
            with transaction.atomic():
                organization = Organization.objects.create(**organization_kwargs)
                new_user = User.objects.create_and_join(
                    organization,
                    email,
                    password,
                    first_name,
                    OrganizationMembership.Level.ADMIN,
                    is_staff=is_staff,
                )
                team = self.create_team(organization)
            self.run_on_team(team, new_user)
            return (organization, team, new_user)
        elif existing_user.is_staff:
            raise exceptions.PermissionDenied("Cannot log in as staff user without password.")
        elif disallow_collision:
            raise exceptions.ValidationError(
                f"Cannot save simulated data - email collision disallowed but there already is an account for {email}."
            )
        else:
            assert existing_user.organization is not None
            assert existing_user.team is not None
            if self.print_steps:
                print(f"Found existing account for {email}.")
            if is_staff and not existing_user.is_staff:
                # Make sure the user is marked as staff - this is for users who signed up normally before
                # and now are logging in securely as a PostHog team member
                existing_user.is_staff = True
                existing_user.save()
            return (existing_user.organization, existing_user.team, existing_user)

    def reset_master(self):
        if self.matrix.is_complete is None:
            self.matrix.simulate()
        master_team = self._prepare_master_team(ensure_blank_slate=True)
        self._save_analytics_data(master_team)
        self._sleep_until_person_data_in_clickhouse(self.MASTER_TEAM_ID)

    @staticmethod
    def create_team(organization: Organization, **kwargs) -> Team:
        team = Team.objects.create(
            organization=organization,
            ingested_event=True,
            completed_snippet_onboarding=True,
            is_demo=True,
            **kwargs,
        )
        return team

    def run_on_team(self, team: Team, user: User):
        if self.print_steps:
            print(f"Saving simulated data...")
        does_clickhouse_data_need_saving = True
        if self.use_pre_save:
            does_clickhouse_data_need_saving = not self._is_demo_data_pre_saved()
            source_team = self._prepare_master_team()
        else:
            source_team = team
        if does_clickhouse_data_need_saving:
            if self.matrix.is_complete is None:
                self.matrix.simulate()
            self._save_analytics_data(source_team)
        if self.use_pre_save:
            self._copy_analytics_data_from_master_team(team)
        self._sync_postgres_with_clickhouse_data(source_team.pk, team.pk)
        self.matrix.set_project_up(team, user)
        if self.print_steps:
            print(f"Inferring taxonomy for Data Management...")
        event_definition_count, property_definition_count, event_properties_count = infer_taxonomy_for_team(team.pk)
        if self.print_steps:
            print(
                f"Inferred {event_definition_count} event definitions, {property_definition_count} property definitions, and {event_properties_count} event-property pairs."
            )
        for cohort in Cohort.objects.filter(team=team):
            cohort.calculate_people_ch(pending_version=0)
        team.save()

    def _save_analytics_data(self, data_team: Team):
        sim_persons = self.matrix.people
        bulk_group_type_mappings = []
        if len(self.matrix.groups.keys()) + self.matrix.group_type_index_offset > 5:
            raise ValueError("Too many group types! The maximum for a project is 5.")
        for group_type_index, (group_type, groups) in enumerate(self.matrix.groups.items()):
            group_type_index += self.matrix.group_type_index_offset  # Adjust
            bulk_group_type_mappings.append(
                GroupTypeMapping(
                    team=data_team,
                    group_type_index=group_type_index,
                    group_type=group_type,
                )
            )
            for group_key, group in groups.items():
                self._save_sim_group(
                    data_team,
                    cast(Literal[0, 1, 2, 3, 4], group_type_index),
                    group_key,
                    group,
                    self.matrix.now,
                )
        try:
            GroupTypeMapping.objects.bulk_create(bulk_group_type_mappings)
        except IntegrityError as e:
            print(f"SKIPPING GROUP TYPE MAPPING CREATION: {e}")
        for sim_person in sim_persons:
            self._save_sim_person(data_team, sim_person)
        # We need to wait a bit for data just queued into Kafka to show up in CH
        self._sleep_until_person_data_in_clickhouse(data_team.pk)

    @classmethod
    def _prepare_master_team(cls, *, ensure_blank_slate: bool = False) -> Team:
        master_team = Team.objects.filter(id=cls.MASTER_TEAM_ID).first()
        if master_team is None:
            master_team = cls._create_master_team()
        elif ensure_blank_slate:
            cls._erase_master_team_data()
        return master_team

    @classmethod
    def _create_master_team(cls) -> Team:
        organization = Organization.objects.create(id=cls.MASTER_TEAM_ID, name="PostHog")
        return cls.create_team(organization, id=cls.MASTER_TEAM_ID, name="Master")

    @classmethod
    def _erase_master_team_data(cls):
        AsyncEventDeletion().process(
            [
                AsyncDeletion(
                    team_id=cls.MASTER_TEAM_ID,
                    key=cls.MASTER_TEAM_ID,
                    deletion_type=DeletionType.Team,
                )
            ]
        )
        GroupTypeMapping.objects.filter(team_id=cls.MASTER_TEAM_ID).delete()

    def _copy_analytics_data_from_master_team(self, target_team: Team):
        from posthog.models.event.sql import COPY_EVENTS_BETWEEN_TEAMS
        from posthog.models.group.sql import COPY_GROUPS_BETWEEN_TEAMS
        from posthog.models.person.sql import (
            COPY_PERSON_DISTINCT_ID2S_BETWEEN_TEAMS,
            COPY_PERSONS_BETWEEN_TEAMS,
        )

        copy_params = {
            "source_team_id": self.MASTER_TEAM_ID,
            "target_team_id": target_team.pk,
        }
        sync_execute(COPY_PERSONS_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_PERSON_DISTINCT_ID2S_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_EVENTS_BETWEEN_TEAMS, copy_params)
        sync_execute(COPY_GROUPS_BETWEEN_TEAMS, copy_params)
        GroupTypeMapping.objects.filter(team_id=target_team.pk).delete()
        GroupTypeMapping.objects.bulk_create(
            (
                GroupTypeMapping(team=target_team, **record)
                for record in GroupTypeMapping.objects.filter(team_id=self.MASTER_TEAM_ID).values(
                    "group_type", "group_type_index", "name_singular", "name_plural"
                )
            ),
        )

    @classmethod
    def _sync_postgres_with_clickhouse_data(cls, source_team_id: int, target_team_id: int):
        from posthog.models.group.sql import SELECT_GROUPS_OF_TEAM
        from posthog.models.person.sql import (
            SELECT_PERSON_DISTINCT_ID2S_OF_TEAM,
            SELECT_PERSONS_OF_TEAM,
        )

        list_params = {"source_team_id": source_team_id}
        # Persons
        clickhouse_persons = query_with_columns(
            SELECT_PERSONS_OF_TEAM,
            list_params,
            ["team_id", "is_deleted", "_timestamp", "_offset", "_partition"],
            {"id": "uuid"},
        )
        bulk_persons: Dict[str, Person] = {}
        for row in clickhouse_persons:
            properties = json.loads(row.pop("properties", "{}"))
            bulk_persons[row["uuid"]] = Person(team_id=target_team_id, properties=properties, **row)
        # This sets the pk in the bulk_persons dict so we can use them later
        Person.objects.bulk_create(bulk_persons.values())
        # Person distinct IDs
        pre_existing_id_count = PersonDistinctId.objects.filter(team_id=target_team_id).count()
        clickhouse_distinct_ids = query_with_columns(
            SELECT_PERSON_DISTINCT_ID2S_OF_TEAM,
            list_params,
            ["team_id", "is_deleted", "_timestamp", "_offset", "_partition"],
            {"person_id": "person_uuid"},
        )
        bulk_person_distinct_ids = []
        for row in clickhouse_distinct_ids:
            person_uuid = row.pop("person_uuid")
            try:
                bulk_person_distinct_ids.append(
                    PersonDistinctId(
                        team_id=target_team_id,
                        person_id=bulk_persons[person_uuid].pk,
                        **row,
                    )
                )
            except KeyError:
                pre_existing_id_count -= 1
        if pre_existing_id_count > 0:
            print(f"{pre_existing_id_count} IDS UNACCOUNTED FOR")
        PersonDistinctId.objects.bulk_create(bulk_person_distinct_ids, ignore_conflicts=True)
        # Groups
        clickhouse_groups = query_with_columns(SELECT_GROUPS_OF_TEAM, list_params, ["team_id", "_timestamp", "_offset"])
        bulk_groups = []
        for row in clickhouse_groups:
            group_properties = json.loads(row.pop("group_properties", "{}"))
            bulk_groups.append(
                Group(
                    team_id=target_team_id,
                    version=0,
                    group_properties=group_properties,
                    **row,
                )
            )
        try:
            Group.objects.bulk_create(bulk_groups)
        except IntegrityError as e:
            print(f"SKIPPING GROUP CREATION: {e}")

    def _save_sim_person(self, team: Team, subject: SimPerson):
        # We only want to save directly if there are past events
        if subject.past_events:
            from posthog.models.person.util import (
                create_person,
                create_person_distinct_id,
            )

            create_person(
                uuid=str(subject.in_posthog_id),
                team_id=team.pk,
                properties=subject.properties_at_now,
                version=0,
            )
            self._persons_created += 1
            self._person_distinct_ids_created += len(subject.distinct_ids_at_now)
            for distinct_id in subject.distinct_ids_at_now:
                create_person_distinct_id(
                    team_id=team.pk,
                    distinct_id=str(distinct_id),
                    person_id=str(subject.in_posthog_id),
                )
            self._save_past_sim_events(team, subject.past_events)
        # We only want to queue future events if there are any
        if subject.future_events and self.matrix.end > self.matrix.now:
            self._save_future_sim_events(team, subject.future_events)

    @staticmethod
    def _save_past_sim_events(team: Team, events: List[SimEvent]):
        """Past events are saved into ClickHouse right away (via Kafka of course)."""
        from posthog.models.event.util import create_event

        for event in events:
            event_uuid = UUIDT(unix_time_ms=int(event.timestamp.timestamp() * 1000))
            create_event(
                event_uuid=event_uuid,
                event=event.event,
                team=team,
                distinct_id=event.distinct_id,
                timestamp=event.timestamp,
                properties=event.properties,
                person_id=event.person_id,
                person_properties=event.person_properties,
                person_created_at=event.person_created_at,
                group0_properties=event.group0_properties,
                group1_properties=event.group1_properties,
                group2_properties=event.group2_properties,
                group3_properties=event.group3_properties,
                group4_properties=event.group4_properties,
                group0_created_at=event.group0_created_at,
                group1_created_at=event.group1_created_at,
                group2_created_at=event.group2_created_at,
                group3_created_at=event.group3_created_at,
                group4_created_at=event.group4_created_at,
            )

    @staticmethod
    def _save_future_sim_events(team: Team, events: List[SimEvent]):
        """Future events are not saved immediately, instead they're scheduled for ingestion via event buffer."""

        # TODO: This used the plugin server's Graphile Worker-based event buffer, but the event buffer is no more

    @staticmethod
    def _save_sim_group(
        team: Team,
        type_index: Literal[0, 1, 2, 3, 4],
        key: str,
        properties: Dict[str, Any],
        timestamp: dt.datetime,
    ):
        from posthog.models.group.util import raw_create_group_ch

        raw_create_group_ch(team.pk, type_index, key, properties, timestamp)

    def _sleep_until_person_data_in_clickhouse(self, team_id: int):
        from posthog.models.person.sql import (
            GET_PERSON_COUNT_FOR_TEAM,
            GET_PERSON_DISTINCT_ID2_COUNT_FOR_TEAM,
        )

        while True:
            person_count: int = sync_execute(GET_PERSON_COUNT_FOR_TEAM, {"team_id": team_id})[0][0]
            person_distinct_id_count: int = sync_execute(GET_PERSON_DISTINCT_ID2_COUNT_FOR_TEAM, {"team_id": team_id})[
                0
            ][0]
            persons_ready = person_count >= self._persons_created
            person_distinct_ids_ready = person_distinct_id_count >= self._person_distinct_ids_created
            persons_progress = f"{'✔' if persons_ready else '✘'} {person_count}/{self._persons_created}"
            person_distinct_ids_progress = f"{'✔' if person_distinct_ids_ready else '✘'} {person_distinct_id_count}/{self._person_distinct_ids_created}"
            if persons_ready and person_distinct_ids_ready:
                if self.print_steps:
                    print(
                        "Source person data fully loaded into ClickHouse. "
                        f"Persons: {persons_progress}. Person distinct IDs: {person_distinct_ids_progress}.\n"
                        "Setting up project..."
                    )
                break
            if self.print_steps:
                print(
                    "Waiting for person data to land in ClickHouse... "
                    f"Persons: {persons_progress}. Person distinct IDs: {person_distinct_ids_progress}."
                )
            sleep(0.5)

    @classmethod
    def _is_demo_data_pre_saved(cls) -> bool:
        return Team.objects.filter(pk=cls.MASTER_TEAM_ID).exists()
