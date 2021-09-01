import uuid
from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.db import connection

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from posthog.models import EventDefinition, Person, Team

UTC_FORMAT = "%Y-%m-%d %H:%M:%S"


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
        self._insert_many_events("2010-01-01 00:00:00")
        self._insert_hours_events("2011-01-01 00:00:00")
        self._insert_days_events("2012-01-01 00:00:00")
        self._insert_weeks_events("2013-01-01 00:00:00")
        self._insert_months_events("2015-01-01 00:00:00")

    def _insert_many_events(self, start_date):
        step_one = self.number + 1
        step_two = round(step_one / 2)
        step_three = round(step_one / 3)
        step_four = round(step_one / 4)
        step_five = round(step_one / 5)

        for i in range(1, step_one):
            create_event(uuid.uuid4(), "step one", self.team, f"user_{i}", start_date)
        for i in range(1, step_two):
            create_event(uuid.uuid4(), "step two", self.team, f"user_{i}", self._add_interval("days", 1, start_date))
        for i in range(1, step_three):
            create_event(uuid.uuid4(), "step three", self.team, f"user_{i}", self._add_interval("days", 2, start_date))
        for i in range(1, step_four):
            create_event(uuid.uuid4(), "step four", self.team, f"user_{i}", self._add_interval("days", 3, start_date))
        for i in range(1, step_five):
            create_event(uuid.uuid4(), "step five", self.team, f"user_{i}", self._add_interval("days", 4, start_date))

    def _insert_hours_events(self, start_date):
        self._case_correct_order("hours", "user_1", start_date)
        self._case_reverse_order("hours", "user_2", start_date)
        self._case_out_of_order_complete("hours", "user_3", start_date)

    def _insert_days_events(self, start_date):
        self._case_correct_order("days", "user_11", start_date)
        self._case_reverse_order("days", "user_12", start_date)
        self._case_out_of_order_complete("days", "user_13", start_date)

    def _insert_weeks_events(self, start_date):
        self._case_correct_order("weeks", "user_21", start_date)
        self._case_reverse_order("weeks", "user_22", start_date)
        self._case_out_of_order_complete("weeks", "user_23", start_date)

    def _insert_months_events(self, start_date):
        self._case_correct_order("months", "user_31", start_date)
        self._case_reverse_order("months", "user_32", start_date)
        self._case_out_of_order_complete("months", "user_33", start_date)

    def _case_correct_order(self, interval, user, start_date):
        create_event(uuid.uuid4(), "step one", self.team, user, start_date)
        create_event(uuid.uuid4(), "step two", self.team, user, self._add_interval(interval, 1, start_date))
        create_event(uuid.uuid4(), "step three", self.team, user, self._add_interval(interval, 2, start_date))
        create_event(uuid.uuid4(), "step four", self.team, user, self._add_interval(interval, 3, start_date))
        create_event(uuid.uuid4(), "step five", self.team, user, self._add_interval(interval, 4, start_date))

    def _case_reverse_order(self, interval, user, start_date):
        create_event(uuid.uuid4(), "step five", self.team, user, start_date)
        create_event(uuid.uuid4(), "step four", self.team, user, self._add_interval(interval, 1, start_date))
        create_event(uuid.uuid4(), "step three", self.team, user, self._add_interval(interval, 2, start_date))
        create_event(uuid.uuid4(), "step two", self.team, user, self._add_interval(interval, 3, start_date))
        create_event(uuid.uuid4(), "step one", self.team, user, self._add_interval(interval, 4, start_date))

    def _case_out_of_order_complete(self, interval, user, start_date):
        create_event(uuid.uuid4(), "step one", self.team, user, start_date)
        create_event(uuid.uuid4(), "step three", self.team, user, self._add_interval(interval, 1, start_date))
        create_event(uuid.uuid4(), "step two", self.team, user, self._add_interval(interval, 1, start_date))
        create_event(uuid.uuid4(), "step three", self.team, user, self._add_interval(interval, 2, start_date))
        create_event(uuid.uuid4(), "step five", self.team, user, self._add_interval(interval, 3, start_date))
        create_event(uuid.uuid4(), "step four", self.team, user, self._add_interval(interval, 3, start_date))
        create_event(uuid.uuid4(), "step five", self.team, user, self._add_interval(interval, 4, start_date))

    def _add_interval(self, interval, delta, date_time_string):
        dt = datetime.strptime(date_time_string, UTC_FORMAT)

        if interval == "months":
            delta = relativedelta(months=delta)
            new_dt = dt + delta
            return new_dt.strftime(UTC_FORMAT)
        elif interval == "weeks":
            delta = relativedelta(weeks=delta)
            new_dt = dt + delta
            return new_dt.strftime(UTC_FORMAT)
        elif interval == "days":
            delta = relativedelta(days=delta)
            new_dt = dt + delta
            return new_dt.strftime(UTC_FORMAT)
        elif interval == "hours":
            delta = relativedelta(hours=delta)
            new_dt = dt + delta
            return new_dt.strftime(UTC_FORMAT)
        else:
            return date_time_string
