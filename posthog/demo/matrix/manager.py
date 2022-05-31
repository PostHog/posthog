import time
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

from posthog.models import (
    EventDefinition,
    EventProperty,
    Group,
    Organization,
    OrganizationMembership,
    Person,
    PersonDistinctId,
    PropertyDefinition,
    Team,
    User,
)
from posthog.models.utils import UUIDT
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team

from .matrix import Matrix
from .models import SimPerson


def save_sim_person(team: Team, subject: SimPerson) -> Optional[Tuple[Person, List[PersonDistinctId]]]:
    if not subject.events:
        return None  # Don't save a person who never participated
    from ee.clickhouse.models.event import create_event
    from ee.clickhouse.models.person import create_person, create_person_distinct_id

    person_uuid_str = str(UUIDT(unix_time_ms=int(subject.events[0].timestamp.timestamp() * 1000)))
    person = Person(team_id=team.pk, properties=subject.properties, uuid=person_uuid_str)
    person_distinct_ids = [
        PersonDistinctId(team_id=team.pk, person=person, distinct_id=distinct_id)
        for distinct_id in subject.distinct_ids
    ]
    create_person(
        uuid=person_uuid_str, team_id=team.pk, properties=subject.properties,
    )
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
    return (person, person_distinct_ids)


def save_sim_group(team: Team, type_index: Literal[0, 1, 2, 3, 4], key: str, properties: Dict[str, Any]) -> Group:
    from ee.clickhouse.models.group import create_group

    return create_group(team.pk, type_index, key, properties)


class MatrixManager:
    @classmethod
    def ensure_account_and_run(
        cls,
        matrix: Matrix,
        email: str,
        first_name: str,
        organization_name: str,
        *,
        password: Optional[str] = None,
        disallow_collision: bool = False,
    ) -> Tuple[Organization, Team, User]:
        """If there's an email collision in signup in the demo environment, we treat it as a login."""
        existing_user = User.objects.filter(email=email).first()
        if existing_user is None:
            organization = Organization.objects.create(name=organization_name)
            new_user = User.objects.create_and_join(
                organization, email, password, first_name, OrganizationMembership.Level.ADMIN
            )
            demo_time = time.time()
            team = MatrixManager.create_team_and_run(matrix, organization, new_user)
            print(f"[DEMO] Prepared in {time.time() - demo_time:.2f} s!")  # noqa: T001
            return (organization, team, new_user)
        elif disallow_collision:
            raise Exception(f"Cannot save simulation data - there already is an account with email {email}.")
        else:
            return (existing_user.organization, existing_user.team, existing_user)

    @classmethod
    def create_team_and_run(cls, matrix: Matrix, organization: Organization, user: User, **kwargs) -> Team:
        team = Team.objects.create(
            organization=organization, ingested_event=True, completed_snippet_onboarding=True, is_demo=True, **kwargs
        )
        return cls.run_on_team(matrix, team, user)

    @classmethod
    def run_on_team(cls, matrix: Matrix, team: Team, user: User) -> Team:
        persons_to_bulk_save: List[Person] = []
        person_distinct_ids_to_bulk_save: List[PersonDistinctId] = []
        simulation_time = time.time()  # FIXME
        if matrix.simulation_complete is None:
            matrix.simulate()
        for group_type_index, groups in enumerate(matrix.groups.values()):
            for group_key, group in groups.items():
                save_sim_group(team, cast(Literal[0, 1, 2, 3, 4], group_type_index), group_key, group)
        sim_persons = matrix.people
        print(f"[DEMO] Simulated {len(sim_persons)} people in {time.time() - simulation_time:.2f} s")
        individual_time = time.time()  # FIXME
        for sim_person in sim_persons:
            sim_person_save_result = save_sim_person(team, sim_person)
            if sim_person_save_result is not None:  # None is returned if the person wasn't ever seen
                persons_to_bulk_save.append(sim_person_save_result[0])
                for distinct_id in sim_person_save_result[1]:
                    person_distinct_ids_to_bulk_save.append(distinct_id)
        print(f"[DEMO] Saved (individual part) {len(sim_persons)} people in {time.time() - individual_time:.2f} s")
        bulk_time = time.time()  # FIXME
        Person.objects.bulk_create(persons_to_bulk_save)
        PersonDistinctId.objects.bulk_create(person_distinct_ids_to_bulk_save)
        print(f"[DEMO] Saved (bulk part) {len(persons_to_bulk_save)} people in {time.time() - bulk_time:.2f} s")
        EventDefinition.objects.bulk_create(
            (
                EventDefinition(team=team, name=event_definition, created_at=matrix.start)
                for event_definition in matrix.event_names
            )
        )
        PropertyDefinition.objects.bulk_create(
            (PropertyDefinition(team=team, name=property_name,) for property_name in matrix.property_names)
        )
        EventProperty.objects.bulk_create(
            (
                EventProperty(team=team, event=event_name, property=property_name,)
                for (event_name, property_name) in matrix.event_property_pairs
            )
        )
        matrix.set_project_up(team, user)
        calculate_event_property_usage_for_team(team.pk)
        set_time = time.time()  # FIXME
        team.save()
        print(f"[DEMO] Setting project up in {time.time() -set_time:.2f} s")
        return team
