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
# 13| set      | yes           | equal                      | set_once    | no
# 14| set_once | yes           | equal                      | set_once    | no

# Refers to migration 0173_should_update_person_props_function
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
                SELECT 
                    should_update_person_prop({person.id}, 'non-existent prop', now()::text, 'set'),
                    should_update_person_prop({person.id}, 'non-existent prop', now()::text, 'set_once')
            """
            )

            result = cursor.fetchall()
            set_op_result = result[0][0]
            set_once_op_result = result[0][1]

            self.assertEqual(set_op_result, True)
            self.assertEqual(set_once_op_result, True)

    def test_update_without_properties_last_operation(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={
                "a": datetime(2050, 1, 1, 1, 1, 1).isoformat(),
                "b": datetime(2050, 1, 1, 1, 1, 1).isoformat(),
            },
            properties_last_operation={},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 
                    should_update_person_prop({person.id}, 'non-existent prop', now()::text, 'set'),
                    should_update_person_prop({person.id}, 'non-existent prop', now()::text, 'set_once')
            """
            )

            result = cursor.fetchall()
            set_op_result = result[0][0]
            set_once_op_result = result[0][1]

            self.assertEqual(set_op_result, True)
            self.assertEqual(set_once_op_result, True)

    # tests cases 1 and 2 from the table
    def test_update_non_existent_prop(self):
        person = Person.objects.create(
            team=self.team, properties={}, properties_last_updated_at={}, properties_last_operation={}
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 
                    should_update_person_prop({person.id}, 'non-existent prop', now()::text, 'set'),
                    should_update_person_prop({person.id}, 'non-existent prop', now()::text, 'set_once')
            """
            )

            result = cursor.fetchall()
            set_op_result = result[0][0]
            set_once_op_result = result[0][1]

            self.assertEqual(set_op_result, True)
            self.assertEqual(set_once_op_result, True)

    # tests cases 3 and 4 from the table
    def test_set_operation_with_earlier_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={
                "a": datetime(2050, 1, 1, 1, 1, 1).isoformat(),
                "b": datetime(2050, 1, 1, 1, 1, 1).isoformat(),
            },
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 
                    should_update_person_prop({person.id}, 'a', now()::text, 'set'),
                    should_update_person_prop({person.id}, 'b', now()::text, 'set')
            """
            )

            result = cursor.fetchall()
            previous_op_set_result = result[0][0]
            previous_op_set_once_result = result[0][1]

            self.assertEqual(previous_op_set_result, False)
            self.assertEqual(previous_op_set_once_result, True)

    # tests cases 5 and 6 from the table
    def test_set_operation_with_older_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={
                "a": datetime(2000, 1, 1, 1, 1, 1).isoformat(),
                "b": datetime(2000, 1, 1, 1, 1, 1).isoformat(),
            },
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 
                    should_update_person_prop({person.id}, 'a', now()::text, 'set'),
                    should_update_person_prop({person.id}, 'b', now()::text, 'set')
            """
            )

            result = cursor.fetchall()
            previous_op_set_result = result[0][0]
            previous_op_set_once_result = result[0][1]

            self.assertEqual(previous_op_set_result, True)
            self.assertEqual(previous_op_set_once_result, True)

    # tests cases 7 and 8 from the table
    def test_set_once_operation_with_earlier_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={
                "a": datetime(2050, 1, 1, 1, 1, 1).isoformat(),
                "b": datetime(2050, 1, 1, 1, 1, 1).isoformat(),
            },
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 
                    should_update_person_prop({person.id}, 'a', now()::text, 'set_once'),
                    should_update_person_prop({person.id}, 'b', now()::text, 'set_once')
            """
            )

            result = cursor.fetchall()
            previous_op_set_result = result[0][0]
            previous_op_set_once_result = result[0][1]

            self.assertEqual(previous_op_set_result, False)
            self.assertEqual(previous_op_set_once_result, True)

    # tests cases 9 and 10 from the table
    def test_set_once_operation_with_older_timestamp(self):
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={
                "a": datetime(2000, 1, 1, 1, 1, 1).isoformat(),
                "b": datetime(2000, 1, 1, 1, 1, 1).isoformat(),
            },
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 
                    should_update_person_prop({person.id}, 'a', now()::text, 'set_once'),
                    should_update_person_prop({person.id}, 'b', now()::text, 'set_once')
            """
            )

            result = cursor.fetchall()
            previous_op_set_result = result[0][0]
            previous_op_set_once_result = result[0][1]

            self.assertEqual(previous_op_set_result, False)
            self.assertEqual(previous_op_set_once_result, False)

    # tests cases 11-14 from the table
    def test_equal_timestamps(self):
        timestamp = datetime(2000, 1, 1, 1, 1, 1).isoformat()
        person = Person.objects.create(
            team=self.team,
            properties={"a": 0, "b": 0},
            properties_last_updated_at={"a": timestamp, "b": timestamp,},
            properties_last_operation={"a": "set", "b": "set_once"},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT 
                    should_update_person_prop({person.id}, 'a', '{timestamp}', 'set_once'),
                    should_update_person_prop({person.id}, 'a', '{timestamp}', 'set'),
                    should_update_person_prop({person.id}, 'b', '{timestamp}', 'set_once'),
                    should_update_person_prop({person.id}, 'b', '{timestamp}', 'set')
            """
            )

            results = cursor.fetchall()[0]

            self.assertEqual(results[0], False)
            self.assertEqual(results[1], False)
            self.assertEqual(results[2], False)
            self.assertEqual(results[3], False)
