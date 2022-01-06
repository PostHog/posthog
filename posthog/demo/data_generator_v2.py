import datetime as dt
import random
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from posthog.models import Action, Organization, Person, PersonDistinctId, Team, User
from posthog.models.utils import UUIDT
from posthog.utils import is_clickhouse_enabled


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    properties: Dict[str, Any]
    timestamp: dt.datetime


@dataclass
class SimSnapshot:
    """A simulated session recording event."""

    snapshot_data: Dict[str, Any]
    session_id: str
    window_id: str
    timestamp: dt.datetime


class SimPerson:
    """A simulated person for creation of demo journeys."""

    team: Team
    first_seen_at: str
    properties: Dict[str, Any]
    events: List[SimEvent]
    snapshots: List[SimSnapshot]

    _first_seen_at: Optional[dt.datetime]
    _saved: bool

    def __init__(self, team: Team):
        self.team = team
        self.properties = {}
        self.events = []
        self.snapshots = []
        self._first_seen_at = None
        self._saved = False

    def add_event(self, event: str, timestamp: dt.datetime, properties: Optional[Dict[str, Any]] = None):
        if self._first_seen_at is None or self._first_seen_at > timestamp:
            self._first_seen_at = timestamp
        if properties:
            if properties.get("$set_once"):
                for key, value in properties["$set_once"].items():
                    if key not in self.properties:
                        self.properties[key] = value
            if properties.get("$set"):
                self.properties.update(properties["$set"])
        self.events.append(SimEvent(event=event, properties=properties or {}, timestamp=timestamp))

    def add_snapshot(self, snapshot_data: Any, session_id: str, window_id: str, timestamp: dt.datetime):
        self.snapshots.append(
            SimSnapshot(snapshot_data=snapshot_data, session_id=session_id, window_id=window_id, timestamp=timestamp)
        )

    def _save(self) -> Tuple[Person, PersonDistinctId]:
        if self._saved:
            raise Exception("Cannot save a SimPerson more than once!")
        self._saved = True

        if not is_clickhouse_enabled():
            raise Exception("Cannot save a SimPerson on ClickHouse-less instance!")
        from ee.clickhouse.models.event import create_event
        from ee.clickhouse.models.person import create_person, create_person_distinct_id
        from ee.clickhouse.models.session_recording_event import create_session_recording_event

        if self._first_seen_at is None:
            raise Exception("Cannot save a SimPerson that has no events!")

        person_uuid_str = str(UUIDT(unix_time_ms=int(self._first_seen_at.timestamp() * 1000)))
        person_distinct_id_str = str(UUIDT(unix_time_ms=int(self._first_seen_at.timestamp() * 1000)))
        person = Person(team=self.team, properties=self.properties, uuid=person_uuid_str)
        person_distinct_id = PersonDistinctId(team=self.team, person=person, distinct_id=person_distinct_id_str)
        create_person(
            uuid=person_uuid_str, team_id=self.team.id, properties=self.properties,
        )
        create_person_distinct_id(team_id=self.team.id, distinct_id=person_distinct_id_str, person_id=person_uuid_str)
        for event in self.events:
            event_uuid = UUIDT(unix_time_ms=int(event.timestamp.timestamp() * 1000))
            create_event(
                event_uuid=event_uuid,
                event=event.event,
                team=self.team,
                distinct_id=person_distinct_id_str,
                timestamp=event.timestamp,
                properties=event.properties,
            )
        for snapshot in self.snapshots:
            snapshot_uuid = UUIDT(unix_time_ms=int(snapshot.timestamp.timestamp() * 1000))
            create_session_recording_event(
                uuid=snapshot_uuid,
                team_id=self.team.id,
                distinct_id=person_distinct_id_str,
                session_id=snapshot.session_id,
                window_id=snapshot.window_id,
                timestamp=snapshot.timestamp,
                snapshot_data=snapshot.snapshot_data,
            )
        return (person, person_distinct_id)


class DataGenerator(ABC):
    n_people: int
    n_days: int
    seed: int

    def __init__(self, *, n_people: int, n_days: int, seed: Optional[int] = None):
        if seed is None:
            seed = random.randint(0, sys.maxsize)
        self.n_people = n_people
        self.n_days = n_days
        self.seed = seed

    def create_team(self, organization: Organization, user: User, simulate_journeys: bool = True, **kwargs) -> Team:
        team = Team.objects.create(
            organization=organization, ingested_event=True, completed_snippet_onboarding=True, is_demo=True, **kwargs
        )
        return self.run_on_team(team, user, simulate_journeys)

    def run_on_team(self, team: Team, user: User, simulate_journeys: bool = True) -> Team:
        self._set_project_up(team, user)
        if simulate_journeys:
            persons_to_bulk_save: List[Person] = []
            person_distinct_ids_to_bulk_save: List[PersonDistinctId] = []
            for i in range(self.n_people):
                person, person_distinct_id = self._create_person_with_journey(team, user, i)._save()
                persons_to_bulk_save.append(person)
                person_distinct_ids_to_bulk_save.append(person_distinct_id)
            Person.objects.bulk_create(persons_to_bulk_save)
            PersonDistinctId.objects.bulk_create(person_distinct_ids_to_bulk_save)
        team.save()
        for action in Action.objects.filter(team=team):
            action.calculate_events()
        return team

    @abstractmethod
    def _set_project_up(self, team: Team, user: User):
        """Project setup, such as insights, dashboards, feature flags, etc. """
        pass

    @abstractmethod
    def _create_person_with_journey(self, team: Team, user: User, index: int) -> SimPerson:
        """Creation of a single person along with their full user journey."""
        pass
