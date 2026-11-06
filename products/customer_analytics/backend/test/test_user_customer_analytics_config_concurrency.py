from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

from posthog.test.base import NonAtomicBaseTest

from django.db import connection

from products.customer_analytics.backend.logic.user_customer_analytics_config import (
    update_pinned_properties,
    update_task_digest,
)
from products.customer_analytics.backend.models import UserCustomerAnalyticsConfig


class TestUserCustomerAnalyticsConfigConcurrency(NonAtomicBaseTest):
    def test_concurrent_preferences_and_pins_preserve_both_changes(self) -> None:
        config = UserCustomerAnalyticsConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            properties={"pinned_properties": [{"kind": "custom_property", "id": "old-pin"}], "unrelated": "kept"},
        )
        read_barrier = Barrier(2, timeout=10)
        team_id, user_id = self.team.id, self.user.id

        def update_preferences(digest: bool) -> None:
            first_read = True

            def synchronize_read(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
                nonlocal first_read
                result = execute(sql, params, many, context)
                if first_read and sql.startswith("SELECT") and UserCustomerAnalyticsConfig._meta.db_table in sql:
                    first_read = False
                    read_barrier.wait()
                return result

            try:
                with connection.execute_wrapper(synchronize_read):
                    if digest:
                        update_task_digest(team_id=team_id, user_id=user_id, enabled=True)
                    else:
                        update_pinned_properties(team_id=team_id, user_id=user_id, references=[])
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(update_preferences, digest) for digest in [False, True]]
            for future in futures:
                future.result(timeout=20)

        config.refresh_from_db()
        self.assertEqual(config.properties["pinned_properties"], [])
        self.assertTrue(config.properties["task_digest"]["enabled"])
        self.assertEqual(config.properties["unrelated"], "kept")
