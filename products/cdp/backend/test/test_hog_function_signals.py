from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from parameterized import parameterized


class TestHogFunctionSignals(BaseTest):
    @parameterized.expand([("commit", False), ("rollback", True)])
    def test_team_filter_refresh_waits_for_commit(self, _name: str, rollback: bool) -> None:
        original_filters = self.team.test_account_filters
        filters = [{"key": "email", "value": "@example.com", "operator": "icontains", "type": "person"}]

        with patch("products.cdp.backend.tasks.hog_functions.refresh_affected_hog_functions.delay") as refresh:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    self.team.test_account_filters = filters
                    self.team.save(update_fields=["test_account_filters"])
                    refresh.assert_not_called()
                    transaction.set_rollback(rollback)

            if rollback:
                refresh.assert_not_called()
            else:
                refresh.assert_called_once_with(team_id=self.team.id)

        self.team.refresh_from_db()
        assert self.team.test_account_filters == (original_filters if rollback else filters)
