import json
from typing import Any

import pytest
from django.test import override_settings

from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.test.base import BaseTest


class TestDatabase(BaseTest):
    snapshot: Any

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_no_person_on_events(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=False):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_with_person_on_events_enabled(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot
