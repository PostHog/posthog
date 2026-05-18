import json

import pytest

from posthog.management.migration_analysis.formatters import JsonFormatter
from posthog.management.migration_analysis.models import MigrationRisk, OperationRisk


def _risk(app: str, name: str, score: int, file_path: str | None = None) -> MigrationRisk:
    return MigrationRisk(
        path=f"{app}.{name}",
        app=app,
        name=name,
        operations=[OperationRisk(type="AddField", score=score, reason="test", details={})],
        file_path=file_path,
    )


class TestJsonFormatter:
    def setup_method(self):
        self.formatter = JsonFormatter()

    def test_empty_report_uses_null_max_level(self):
        report = json.loads(self.formatter.format_report([]))

        assert report == {
            "summary": {"safe": 0, "needs_review": 0, "blocked": 0},
            "max_level": None,
            "migrations": [],
        }

    def test_single_migration_full_shape(self):
        """Pins the full output contract for the simplest non-empty case,
        including the `app.name` label format and the `file_path` field that
        stamphog uses to scope its deny-list bypass."""
        report = json.loads(
            self.formatter.format_report(
                [_risk("posthog", "1125_x", score=1, file_path="posthog/migrations/1125_x.py")]
            )
        )

        assert report == {
            "summary": {"safe": 1, "needs_review": 0, "blocked": 0},
            "max_level": "Safe",
            "migrations": [{"label": "posthog.1125_x", "level": "Safe", "file_path": "posthog/migrations/1125_x.py"}],
        }

    def test_missing_file_path_emits_null(self):
        """When the command can't resolve a disk path (frozen apps, weird
        loaders), `file_path` is null rather than absent — keeps the schema
        shape stable for consumers."""
        report = json.loads(self.formatter.format_report([_risk("posthog", "1125_x", score=1)]))

        assert report["migrations"] == [{"label": "posthog.1125_x", "level": "Safe", "file_path": None}]

    @pytest.mark.parametrize(
        "scores, expected_max_level",
        [
            pytest.param([0, 1], "Safe", id="all-safe"),
            pytest.param([1, 3], "Needs Review", id="needs-review-when-no-blocked"),
            pytest.param([1, 2, 4], "Blocked", id="blocked-wins-over-everything"),
        ],
    )
    def test_max_level_picks_highest_severity_present(self, scores: list[int], expected_max_level: str):
        """`max_level` is what stamphog and the GitHub check read — must always
        reflect the worst migration in the batch."""
        results = [_risk("posthog", f"m{i}", score=s) for i, s in enumerate(scores)]

        report = json.loads(self.formatter.format_report(results))

        assert report["max_level"] == expected_max_level
