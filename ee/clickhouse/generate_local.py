import uuid

from django.db import connection

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from posthog.models import EventDefinition, Person, Team


class GenerateLocal:
    team: Team
    number: int

    def __init__(self, team, number=250):
        self.team = team
        self.number = number

    def generate(self):
        self._insert_persons()
        self._insert_event_definitions()
        self._insert_events()

    def destroy(self):
        # You'll need to manually clean up the clickhouse database by:
        # 1. docker compose -f ee/docker-compose.ch.yml down clickhouse zookeeper kafka
        # 2. DEBUG=1;DJANGO_SETTINGS_MODULE=posthog.settings;PRIMARY_DB=clickhouse;CLICKHOUSE_HOST=clickhouse;CLICKHOUSE_DATABASE=posthog;CLICKHOUSE_SECURE=false;CLICKHOUSE_VERIFY=false python migrate.py migrate_clickhouse

        with connection.cursor() as cursor:
            cursor.execute("delete from posthog_persondistinctid where distinct_id like 'user_%%'")
            cursor.execute("delete from posthog_person where properties->> 'name' like 'user_%'")
            cursor.execute("delete from posthog_eventdefinition where name like 'step %'")

    def _insert_event_definitions(self):
        EventDefinition.objects.get_or_create(team=self.team, name="step one")
        EventDefinition.objects.get_or_create(team=self.team, name="step two")
        EventDefinition.objects.get_or_create(team=self.team, name="step three")
        EventDefinition.objects.get_or_create(team=self.team, name="step four")
        EventDefinition.objects.get_or_create(team=self.team, name="step five")

    def _insert_persons(self):
        for i in range(1, self.number + 1):
            try:
                person = Person.objects.create(
                    distinct_ids=[f"user_{i}"], team=self.team, properties={"name": f"user_{i}"}
                )
                self._insert_person_distinct_ids(f"user_{i}", person.uuid)
            except Exception as e:
                print(str(e))

    def _insert_person_distinct_ids(self, distinct_id, person_uuid):
        sql = f"""
        insert into person_distinct_id (distinct_id, person_id, team_id, _timestamp) values
        ('{distinct_id}', '{person_uuid}', '{self.team.id}', now());
        """

        sync_execute(sql)

    def _insert_events(self):
        step_one = self.number + 1
        step_two = round(step_one / 2)
        step_three = round(step_one / 3)
        step_four = round(step_one / 4)
        step_five = round(step_one / 5)

        for i in range(1, step_one):
            create_event(uuid.uuid4(), "step one", self.team, f"user_{i}", "2021-05-01 00:00:00")
        for i in range(1, step_two):
            create_event(uuid.uuid4(), "step two", self.team, f"user_{i}", "2021-05-03 00:00:00")
        for i in range(1, step_three):
            create_event(uuid.uuid4(), "step three", self.team, f"user_{i}", "2021-05-05 00:00:00")
        for i in range(1, step_four):
            create_event(uuid.uuid4(), "step four", self.team, f"user_{i}", "2021-05-07 00:00:00")
        for i in range(1, step_five):
            create_event(uuid.uuid4(), "step five", self.team, f"user_{i}", "2021-05-09 00:00:00")
