import json

from posthog.management.migration_analysis.formatters import JsonFormatter
from posthog.management.migration_analysis.models import MigrationRisk, OperationRisk


def _risk(app: str, name: str, score: int) -> MigrationRisk:
    return MigrationRisk(
        path=f"{app}.{name}",
        app=app,
        name=name,
        operations=[OperationRisk(type="AddField", score=score, reason="test", details={})],
    )


class TestJsonFormatter:
    def setup_method(self):
        self.formatter = JsonFormatter()

    def test_empty_report(self):
        report = json.loads(self.formatter.format_report([]))

        assert report == {
            "summary": {"safe": 0, "needs_review": 0, "blocked": 0},
            "max_level": None,
            "migrations": [],
        }

    def test_single_safe_migration(self):
        report = json.loads(self.formatter.format_report([_risk("posthog", "1125_x", score=1)]))

        assert report == {
            "summary": {"safe": 1, "needs_review": 0, "blocked": 0},
            "max_level": "Safe",
            "migrations": [{"label": "posthog.1125_x", "level": "Safe"}],
        }

    def test_max_level_picks_highest_severity(self):
        results = [
            _risk("posthog", "1125_safe", score=1),
            _risk("posthog", "1126_review", score=2),
            _risk("posthog", "1127_blocked", score=4),
        ]

        report = json.loads(self.formatter.format_report(results))

        assert report["summary"] == {"safe": 1, "needs_review": 1, "blocked": 1}
        assert report["max_level"] == "Blocked"

    def test_max_level_safe_when_all_safe(self):
        results = [_risk("posthog", "1125_x", score=0), _risk("posthog", "1126_y", score=1)]

        report = json.loads(self.formatter.format_report(results))

        assert report["max_level"] == "Safe"

    def test_max_level_needs_review_when_no_blocked(self):
        results = [_risk("posthog", "1125_x", score=1), _risk("posthog", "1126_y", score=3)]

        report = json.loads(self.formatter.format_report(results))

        assert report["max_level"] == "Needs Review"

    def test_label_uses_app_dot_name_format(self):
        results = [_risk("signals", "0042_choice_update", score=0)]

        report = json.loads(self.formatter.format_report(results))

        assert report["migrations"][0]["label"] == "signals.0042_choice_update"
