from posthog.test.base import BaseTest

from posthog.models import GroupUsageMetric


class GroupUsageMetricTestCase(BaseTest):
    def test_bytecode_generation(self):
        metric = GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="test",
            filters={
                "events": [
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                ],
                "actions": [],
                "filter_test_accounts": True,
            },
        )

        self.assertIsNotNone(metric.bytecode)
        self.assertIsNone(metric.bytecode_error)
        assert isinstance(metric.bytecode, list)  # Using assert to help mypy with the types
        self.assertGreater(len(metric.bytecode), 0)
