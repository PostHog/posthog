from django.test import override_settings

from posthog.hogql.database import create_hogql_database, serialize_database
from posthog.test.base import BaseTest


class TestDatabase(BaseTest):
    def test_serialize_database(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=False):
            json = serialize_database(create_hogql_database(team_id=self.team.pk))
            self.assertEqual(json, {})
