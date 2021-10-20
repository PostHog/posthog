from datetime import datetime

from django.db import connection

from posthog.models import Person
from posthog.test.base import BaseTest

# How we expect this function to behave:
#   | call     | value exists  | call TS is ___ existing TS | previous fn | write/override
#  1| set      | no            | N/A                        | N/A         | yes
#  2| set_once | no            | N/A                        | N/A         | yes
#  3| set      | yes           | before                     | set         | no
#  4| set      | yes           | before                     | set_once    | yes
#  5| set      | yes           | after                      | set         | yes
#  6| set      | yes           | after                      | set_once    | yes
#  7| set_once | yes           | before                     | set         | no
#  8| set_once | yes           | before                     | set_once    | yes
#  9| set_once | yes           | after                      | set         | no
# 10| set_once | yes           | after                      | set_once    | no
# 11| set      | yes           | equal                      | set         | no
# 12| set_once | yes           | equal                      | set         | no
# 13| set      | yes           | equal                      | set_once    | yes
# 14| set_once | yes           | equal                      | set_once    | no


FUTURE_TIMESTAMP = datetime(2050, 1, 1, 1, 1, 1).isoformat()
PAST_TIMESTAMP = datetime(2000, 1, 1, 1, 1, 1).isoformat()

# Refers to migration 0176_update_person_props_function
# This is a Postgres function we use in the plugin server
class TestShouldUpdatePersonProp(BaseTest):
    def test_update_without_properties_last_updated_at(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={},
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                now()::text, 
	                array[
                        row('set', 'a', '1'::jsonb)::person_property_update, 
                        row('set_once', 'b', '1'::jsonb)::person_property_update
                    ]
                ) 
            """
            )

        updated_person = Person.objects.get(id=person.id)

        # dont update set_once call
        self.assertEqual(updated_person.properties, {"a": 1, "b": 0})
        self.assertEqual(updated_person.properties_last_operation, {"a": "set", "b": "set_once"})
        self.assertIsNotNone(updated_person.properties_last_updated_at["a"])

    def test_update_without_properties_last_operation(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={"a": FUTURE_TIMESTAMP, "b": FUTURE_TIMESTAMP,},
            properties_last_operation={},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                now()::text, 
	                array[
                        row('set', 'a', '1'::jsonb)::person_property_update, 
                        row('set_once', 'b', '1'::jsonb)::person_property_update
                    ]
                ) 
            """
            )

        updated_person = Person.objects.get(id=person.id)

        # dont update set_once call
        self.assertEqual(updated_person.properties, {"a": 1, "b": 0})
        self.assertEqual(updated_person.properties_last_operation, {"a": "set"})
        self.assertNotEqual(updated_person.properties_last_updated_at["a"], FUTURE_TIMESTAMP)

    # tests cases 1 and 2 from the table
    def test_update_non_existent_prop(self):
        person = Person.objects.create(
            team=self.team, properties={}, properties_last_updated_at={}, properties_last_operation={}
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                now()::text, 
	                array[
                        row('set', 'a', '1'::jsonb)::person_property_update, 
                        row('set_once', 'b', '1'::jsonb)::person_property_update
                    ]
                ) 
                """
            )

        updated_person = Person.objects.get(id=person.id)

        # both updated
        self.assertEqual(updated_person.properties, {"a": 1, "b": 1})
        self.assertEqual(updated_person.properties_last_operation, {"a": "set", "b": "set_once"})
        self.assertIsNotNone(updated_person.properties_last_updated_at["a"])
        self.assertIsNotNone(updated_person.properties_last_updated_at["b"])

    # # tests cases 3 and 4 from the table
    def test_set_operation_with_earlier_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={"a": FUTURE_TIMESTAMP, "b": FUTURE_TIMESTAMP,},
            properties_last_operation={"a": "set", "b": "set_once"},
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                now()::text, 
	                array[
                        row('set', 'a', '1'::jsonb)::person_property_update, 
                        row('set', 'b', '1'::jsonb)::person_property_update
                    ]
                ) 
            """
            )

        updated_person = Person.objects.get(id=person.id)

        # b updated
        self.assertEqual(updated_person.properties, {"a": 0, "b": 1})
        self.assertEqual(updated_person.properties_last_operation, {"a": "set", "b": "set"})
        self.assertEqual(updated_person.properties_last_updated_at["a"], FUTURE_TIMESTAMP)
        self.assertNotEqual(updated_person.properties_last_updated_at["b"], FUTURE_TIMESTAMP)

    # # tests cases 5 and 6 from the table
    def test_set_operation_with_older_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={"a": PAST_TIMESTAMP, "b": PAST_TIMESTAMP,},
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                now()::text, 
	                array[
                        row('set', 'a', '1'::jsonb)::person_property_update, 
                        row('set', 'b', '1'::jsonb)::person_property_update
                    ]
                ) 
            """
            )

        updated_person = Person.objects.get(id=person.id)

        # both updated
        self.assertEqual(updated_person.properties, {"a": 1, "b": 1})
        self.assertEqual(updated_person.properties_last_operation, {"a": "set", "b": "set"})
        self.assertNotEqual(updated_person.properties_last_updated_at["a"], PAST_TIMESTAMP)
        self.assertNotEqual(updated_person.properties_last_updated_at["b"], PAST_TIMESTAMP)

    # tests cases 7 and 8 from the table
    def test_set_once_operation_with_earlier_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={"a": FUTURE_TIMESTAMP, "b": FUTURE_TIMESTAMP,},
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                now()::text, 
	                array[
                        row('set_once', 'a', '1'::jsonb)::person_property_update, 
                        row('set_once', 'b', '1'::jsonb)::person_property_update
                    ]
                ) 
            """
            )

        updated_person = Person.objects.get(id=person.id)

        # b updated
        self.assertEqual(updated_person.properties, {"a": 0, "b": 1})
        self.assertEqual(updated_person.properties_last_operation, {"a": "set", "b": "set_once"})
        self.assertEqual(updated_person.properties_last_updated_at["a"], FUTURE_TIMESTAMP)
        self.assertNotEqual(updated_person.properties_last_updated_at["b"], FUTURE_TIMESTAMP)

    # tests cases 9 and 10 from the table
    def test_set_once_operation_with_older_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={"a": PAST_TIMESTAMP, "b": PAST_TIMESTAMP,},
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                now()::text, 
	                array[
                        row('set_once', 'a', '1'::jsonb)::person_property_update, 
                        row('set_once', 'b', '1'::jsonb)::person_property_update
                    ]
                ) 
            """
            )

        updated_person = Person.objects.get(id=person.id)

        # neither updated
        self.assertEqual(updated_person.properties, {"a": 0, "b": 0})
        self.assertEqual(updated_person.properties_last_operation, {"a": "set", "b": "set_once"})
        self.assertEqual(updated_person.properties_last_updated_at["a"], PAST_TIMESTAMP)
        self.assertEqual(updated_person.properties_last_updated_at["b"], PAST_TIMESTAMP)

    # # tests cases 11-14 from the table
    def test_equal_timestamps(self):
        timestamp = PAST_TIMESTAMP
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0, "c": 0, "d": 0},
            properties_last_updated_at={"a": timestamp, "b": timestamp, "c": timestamp, "d": timestamp},
            properties_last_operation={"a": "set", "b": "set", "c": "set_once", "d": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT update_person_props(
	                {person.id}, 
	                '{timestamp}', 
	                array[
                        row('set', 'a', '1'::jsonb)::person_property_update, 
                        row('set_once', 'b', '1'::jsonb)::person_property_update,
                        row('set', 'c', '1'::jsonb)::person_property_update,
                        row('set_once', 'd', '1'::jsonb)::person_property_update
                    ]
                ) 
            """
            )

        updated_person = Person.objects.get(id=person.id)

        # update if current op is set and last op is set_once i.e. "c"
        self.assertEqual(updated_person.properties, {"a": 0, "b": 0, "c": 1, "d": 0})
        self.assertEqual(
            updated_person.properties_last_operation, {"a": "set", "b": "set", "c": "set", "d": "set_once"}
        )  # c changed
        self.assertEqual(updated_person.properties_last_updated_at["a"], PAST_TIMESTAMP)
        self.assertEqual(updated_person.properties_last_updated_at["b"], PAST_TIMESTAMP)
        self.assertEqual(updated_person.properties_last_updated_at["c"], PAST_TIMESTAMP)
        self.assertEqual(updated_person.properties_last_updated_at["c"], PAST_TIMESTAMP)
