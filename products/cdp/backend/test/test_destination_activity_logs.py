from posthog.test.base import BaseTest

from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.services.destination_activity_logs import (
    ActivityLogScope,
    count_unmasked_activity_logs,
    mask_activity_logs,
)


class TestDestinationActivityLogs(BaseTest):
    def _log(self, scope: str, changes: list[dict]) -> ActivityLog:
        return ActivityLog.objects.create(
            team_id=self.team.pk,
            organization_id=self.organization.pk,
            user=self.user,
            scope=scope,
            activity="updated",
            item_id="1",
            detail={"name": "example", "changes": changes},
        )

    def test_masks_destination_values_and_keeps_everything_else(self) -> None:
        destination = self._log(
            "HogFunction",
            [
                {
                    "type": "HogFunction",
                    "field": "inputs",
                    "action": "changed",
                    "before": {"api_key": {"value": "key-1"}},
                    "after": {"api_key": {"value": "key-2"}},
                },
                {
                    "type": "HogFunction",
                    "field": "mappings",
                    "action": "changed",
                    "before": None,
                    "after": [{"inputs": {"token": {"value": "token-1"}}}],
                },
                {
                    "type": "HogFunction",
                    "field": "transpiled",
                    "action": "changed",
                    "before": "old",
                    "after": 'const key = "key-2"',
                },
                {"type": "HogFunction", "field": "description", "action": "changed", "before": "a", "after": "b"},
            ],
        )
        already_masked = self._log(
            "HogFunction",
            [{"type": "HogFunction", "field": "inputs", "action": "changed", "before": "masked", "after": "masked"}],
        )
        flag = self._log(
            "FeatureFlag",
            [{"type": "FeatureFlag", "field": "filters", "action": "changed", "before": {"a": 1}, "after": {"a": 2}}],
        )
        untouched = {log.pk: log.detail for log in (already_masked, flag)}
        scope = ActivityLogScope(team_id=self.team.pk, batch_size=1)

        assert count_unmasked_activity_logs(scope).rows == 1
        assert mask_activity_logs(scope) == 1

        destination.refresh_from_db()
        assert destination.detail is not None
        assert [(c["field"], c.get("before"), c.get("after")) for c in destination.detail["changes"]] == [
            ("inputs", "masked", "masked"),
            ("mappings", None, "masked"),
            ("transpiled", "masked", "masked"),
            ("description", "a", "b"),
        ]
        assert {log.pk: log.detail for log in ActivityLog.objects.filter(pk__in=untouched)} == untouched
        assert count_unmasked_activity_logs(scope).rows == 0
