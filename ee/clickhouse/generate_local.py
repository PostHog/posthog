import uuid

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from posthog.models import EventDefinition, Person, Team


class GenerateLocal:
    _team: None
    _number: None

    def __init__(self, team_id=1, number=250):
        self._team = Team.objects.get(id=team_id)
        self._number = number

    def generate(self):
        self._insert_persons()
        self._insert_person_distinct_ids()
        self._insert_event_definitions()
        self._insert_events()

    def destroy(self):
        # TODO
        # You'll need to manually clean up the clickhouse database
        pass

    def _insert_event_definitions(self):
        EventDefinition.objects.get_or_create(team=self._team, name="step one")
        EventDefinition.objects.get_or_create(team=self._team, name="step two")
        EventDefinition.objects.get_or_create(team=self._team, name="step three")
        EventDefinition.objects.get_or_create(team=self._team, name="step four")
        EventDefinition.objects.get_or_create(team=self._team, name="step five")

    def _insert_persons(self):
        for i in range(self._number):
            try:
                Person.objects.create(distinct_ids=[f"user_{i}"], team=self._team)
            except Exception as e:
                print(str(e))

    def _insert_person_distinct_ids(self):
        values = []
        for i in range(self._number):
            values.append(f"('user_{i}', generateUUIDv4(), {self._team.id}, now())")

        sql = f"""
        insert into person_distinct_id (distinct_id, person_id, team_id, _timestamp) values {",".join(values)};
        """

        sync_execute(sql)

    def _insert_events(self):
        for i in range(self._number):
            create_event(uuid.uuid4(), "step one", self._team, f"user_{i}", "2021-05-01 00:00:00")
            create_event(uuid.uuid4(), "step two", self._team, f"user_{i}", "2021-05-03 00:00:00")
            create_event(uuid.uuid4(), "step three", self._team, f"user_{i}", "2021-05-05 00:00:00")
            create_event(uuid.uuid4(), "step four", self._team, f"user_{i}", "2021-05-07 00:00:00")
            create_event(uuid.uuid4(), "step five", self._team, f"user_{i}", "2021-05-09 00:00:00")
