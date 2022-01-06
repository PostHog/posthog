import datetime as dt
import random
import sys
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from posthog.models import Action, Organization, Person, Team, User

try:
    from ee.clickhouse.models.event import create_event
    from ee.clickhouse.models.person import create_person, create_person_distinct_id
    from ee.clickhouse.models.session_recording_event import create_session_recording_event
except ImportError:
    pass


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

    DUPLICATED_INITIAL_PROPERTIES = [
        "current_url",
        "referrer",
        "referring_domain",
        "device_type",
        "geoip_latitude",
        "geoip_city_name",
        "geoip_longitude",
        "geoip_time_zone",
        "geoip_postal_code",
        "geoip_country_code",
        "geoip_country_name",
        "geoip_continent_code",
        "geoip_continent_name",
    ]

    team: Team
    uuid: str
    distinct_id: str
    properties: Dict[str, Any]
    events: List[SimEvent]
    snapshots: List[SimSnapshot]

    _saved: bool

    def __init__(self, team: Team):
        self.team = team
        self.uuid = str(uuid.uuid4())
        self.distinct_id = str(uuid.uuid4())
        self.properties = {}
        self.events = []
        self.snapshots = []
        self._saved = False

    def add_event(self, event: str, timestamp: dt.datetime, properties: Optional[Dict[str, Any]] = None):
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

    def _save(self):
        if self._saved:
            raise Exception("Cannot save a SimPerson more than once!")
        self._saved = True
        now = dt.datetime.now()
        person = Person.objects.create(
            team=self.team, properties=self.properties, uuid=self.uuid, distinct_ids=[self.distinct_id]
        )
        create_person(
            uuid=self.uuid, team_id=self.team.id, properties=self.properties,
        )
        create_person_distinct_id(team_id=self.team.id, distinct_id=self.distinct_id, person_id=person.id)
        for event in self.events:
            if event.timestamp > now:
                break  # Skip events that are in the future
            create_event(
                event_uuid=uuid.uuid4(),
                event=event.event,
                team=self.team,
                distinct_id=self.distinct_id,
                timestamp=event.timestamp,
                properties=event.properties,
            )
        for snapshot in self.snapshots:
            if snapshot.timestamp > now:
                break  # Skip snapshots that are in the future
            create_session_recording_event(
                uuid=uuid.uuid4(),
                team_id=self.team.id,
                distinct_id=self.distinct_id,
                session_id=snapshot.session_id,
                window_id=snapshot.window_id,
                timestamp=snapshot.timestamp,
                snapshot_data=snapshot.snapshot_data,
            )
        return person


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
            for i in range(self.n_people):
                self._create_person_with_journey(team, user, i)._save()
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
