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
except ImportError:
    pass


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    properties: Dict[str, Any]
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

    _saved: bool

    def __init__(self, team: Team):
        self.team = team
        self.uuid = str(uuid.uuid4())
        self.distinct_id = str(uuid.uuid4())
        self.properties = {}
        self.events = []
        self._saved = False

    def add_event(self, event: str, properties: Dict[str, Any], timestamp: dt.datetime):
        if properties:
            if properties.get("$set_once"):
                for key, value in properties["$set_once"].items():
                    if key not in self.properties:
                        self.properties[key] = value
            if properties.get("$set"):
                self.properties.update(properties["$set"])
        self.events.append(SimEvent(event=event, properties=properties, timestamp=timestamp))

    def _save(self):
        if self._saved:
            raise Exception("Cannot save a SimPerson more than once!")
        self._saved = True
        person = Person.objects.create(
            team=self.team, properties=self.properties, uuid=self.uuid, distinct_ids=[self.distinct_id]
        )
        create_person(
            uuid=self.uuid, team_id=self.team.id, properties=self.properties,
        )
        create_person_distinct_id(team_id=self.team.id, distinct_id=self.distinct_id, person_id=person.id)
        for event in self.events:
            create_event(
                event_uuid=uuid.uuid4(),
                event=event.event,
                team=self.team,
                distinct_id=self.distinct_id,
                timestamp=event.timestamp,
                properties=event.properties,
            )
        return person


class DataGenerator(ABC):
    n_people: int
    seed: int

    def __init__(self, *, n_people: int, seed: Optional[int] = None):
        if seed is None:
            seed = random.randint(0, sys.maxsize)
        self.n_people = n_people
        self.seed = seed

    def create_team(self, organization: Organization, user: User) -> Team:
        team = Team.objects.create(
            organization=organization, ingested_event=True, completed_snippet_onboarding=True, is_demo=True,
        )
        self._set_project_up(team, user)
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
