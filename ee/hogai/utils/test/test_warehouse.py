from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from ee.hogai.utils.warehouse import serialize_database_schema


class TestSerializeDatabaseSchema(BaseTest):
    def test_includes_sessions_logs_and_posthog_namespace_alongside_core_tables(self):
        database = Database.create_for(team=self.team, user=self.user)
        context = HogQLContext(team=self.team, user=self.user, database=database, enable_select_queries=True)
        schema = async_to_sync(serialize_database_schema)(database, context)

        # Regression: `sessions`, `logs`, and the `posthog.*` namespace were omitted from `include_only`,
        # so Max never saw a field list for them and guessed table/field names (`session_id`, bare
        # `ai_events`) when asked about sessions, logs, or AI events.
        self.assertIn("Table `sessions` with fields:", schema)
        self.assertIn("Table `logs` with fields:", schema)
        self.assertIn("Table `posthog.ai_events` with fields:", schema)

        # Widening the set must not drop the core tables that already worked.
        self.assertIn("Table `events` with fields:", schema)
        self.assertIn("Table `persons` with fields:", schema)
        self.assertIn("Table `groups` with fields:", schema)
