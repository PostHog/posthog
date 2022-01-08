import time
from abc import ABC
from typing import List, Optional, Tuple

from posthog.models import (
    Action,
    Group,
    GroupTypeMapping,
    Organization,
    Person,
    PersonDistinctId,
    Team,
    User,
)
from posthog.models.utils import UUIDT

from .models import SimGroup, SimPerson
from .simulation import Matrix


def save_person(team_id: int, subject: SimPerson) -> Optional[Tuple[Person, PersonDistinctId]]:
    if subject.first_seen_at is None:
        return  # Don't save a person who never participated
    from ee.clickhouse.models.event import create_event
    from ee.clickhouse.models.person import create_person, create_person_distinct_id
    from ee.clickhouse.models.session_recording_event import create_session_recording_event

    person_uuid_str = str(UUIDT(unix_time_ms=int(subject.first_seen_at.timestamp() * 1000)))
    person_distinct_id_str = str(UUIDT(unix_time_ms=int(subject.first_seen_at.timestamp() * 1000)))
    person = Person(team_id=team_id, properties=subject.properties, uuid=person_uuid_str)
    person_distinct_id = PersonDistinctId(team_id=team_id, person=person, distinct_id=person_distinct_id_str)
    create_person(
        uuid=person_uuid_str, team_id=team_id, properties=subject.properties,
    )
    create_person_distinct_id(team_id=team_id, distinct_id=person_distinct_id_str, person_id=person_uuid_str)
    for event in subject.events:
        event_uuid = UUIDT(unix_time_ms=int(event.timestamp.timestamp() * 1000))
        create_event(
            event_uuid=event_uuid,
            event=event.event,
            team=team_id,
            distinct_id=person_distinct_id_str,
            timestamp=event.timestamp,
            properties=event.properties,
        )
    for snapshot in subject.snapshots:
        snapshot_uuid = UUIDT(unix_time_ms=int(snapshot.timestamp.timestamp() * 1000))
        create_session_recording_event(
            uuid=snapshot_uuid,
            team_id=team_id,
            distinct_id=person_distinct_id_str,
            session_id=snapshot.session_id,
            window_id=snapshot.window_id,
            timestamp=snapshot.timestamp,
            snapshot_data=snapshot.snapshot_data,
        )
    return (person, person_distinct_id)


def save_group(team_id: int, subject: SimGroup) -> Group:
    from ee.clickhouse.models.group import create_group

    return create_group(team_id, subject.type_index, subject.key, subject.properties)


class MatrixManager(ABC):
    @classmethod
    def create_team(
        cls, matrix: Matrix, organization: Organization, user: User, simulate_journeys: bool = True, **kwargs
    ) -> Team:
        team = Team.objects.create(
            organization=organization, ingested_event=True, completed_snippet_onboarding=True, is_demo=True, **kwargs
        )
        return cls.run_on_team(matrix, team, user, simulate_journeys)

    @classmethod
    def run_on_team(cls, matrix: Matrix, team: Team, user: User, simulate_journeys: bool = True) -> Team:
        set_time = time.time()  # rm
        matrix.set_project_up(team, user)
        print(f"[DEMO] Setting project up in {time.time() -set_time}")  # rm
        if simulate_journeys:
            persons_to_bulk_save: List[Person] = []
            person_distinct_ids_to_bulk_save: List[PersonDistinctId] = []
            matrix.simulate()
            simulation_time = time.time()  # rm
            sim_persons, sim_groups = matrix.people, matrix.groups
            print(f"[DEMO] Simulated {len(sim_persons)} people in {time.time() - simulation_time}")  # rm
            individual_time = time.time()  # rm
            for sim_group in sim_groups:
                save_group(team.id, sim_group)
            for sim_person in sim_persons:
                sim_person_save_result = save_person(team.id, sim_person)
                if sim_person_save_result is not None:  # None is returned if the person wasn't ever seen
                    persons_to_bulk_save.append(sim_person_save_result[0])
                    person_distinct_ids_to_bulk_save.append(sim_person_save_result[1])
            print(f"[DEMO] Saved (individual part) {len(sim_persons)} people in {time.time() - individual_time}")  # rm
            bulk_time = time.time()  # rm
            Person.objects.bulk_create(persons_to_bulk_save)
            PersonDistinctId.objects.bulk_create(person_distinct_ids_to_bulk_save)
            print(f"[DEMO] Saved (bulk part) {len(persons_to_bulk_save)} people in {time.time() - bulk_time}")  # rm
        team.save()
        for action in Action.objects.filter(team=team):
            action.calculate_events()
        return team
