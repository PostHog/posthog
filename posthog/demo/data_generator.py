import json
import random
import secrets
from pathlib import Path
from typing import Dict, List

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from rest_framework.request import Request

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.ee import is_ee_enabled
from posthog.models import (
    Action,
    ActionStep,
    Dashboard,
    DashboardItem,
    Element,
    Event,
    FeatureFlag,
    Organization,
    Person,
    PersonDistinctId,
    Team,
    User,
)
from posthog.models.utils import UUIDT
from posthog.utils import render_template


class DataGenerator:
    def __init__(self, team: Team, n_days=14, n_people=100):
        self.team = team
        self.n_days = n_days
        self.n_people = n_people
        self.events = []
        self.distinct_ids = []

    def create(self):
        self.create_missing_events_and_properties()
        self.create_people()

        for index, (person, distinct_id) in enumerate(zip(self.people, self.distinct_ids)):
            self.populate_person_events(person, distinct_id, index)

        self.bulk_import_events()
        self.create_actions_dashboards()
        _recalculate(team=self.team)

    def create_people(self):
        self.people = [Person(team=self.team, properties={"is_demo": True}) for _ in range(self.n_people)]
        self.distinct_ids = [str(UUIDT()) for _ in self.people]

        Person.objects.bulk_create(self.people)
        PersonDistinctId.objects.bulk_create(
            [
                PersonDistinctId(team=self.team, person=person, distinct_id=distinct_id)
                for person, distinct_id in zip(self.people, self.distinct_ids)
            ]
        )

    def create_missing_events_and_properties(self):
        raise NotImplementedError("You need to implement run")

    def create_actions_dashboards(self):
        raise NotImplementedError("You need to implement run")

    def populate_person_events(self, person: Person, distinct_id: str, _index: int):
        raise NotImplementedError("You need to implement run")

    def bulk_import_events(self):
        if is_ee_enabled():
            from ee.clickhouse.demo import bulk_create_events

            bulk_create_events(self.events, team=self.team)
        else:
            Event.objects.bulk_create([Event(**kw, team=self.team) for kw in self.events])

    def add_event(self, **kw):
        self.events.append(kw)

    def add_if_not_contained(self, array, value):
        if value not in array:
            array.append(value)


def _recalculate(team: Team) -> None:
    actions = Action.objects.filter(team=team)
    for action in actions:
        action.calculate_events()
