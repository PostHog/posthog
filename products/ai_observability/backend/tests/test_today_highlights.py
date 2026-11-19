from datetime import UTC, date, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import User

from products.access_control.backend.facade.testing import create_access_control
from products.ai_observability.backend import today_highlights
from products.ai_observability.backend.facade.today_highlights import HIGHLIGHT_SOURCES
from products.ai_observability.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
from products.ai_observability.backend.models.evaluations import Evaluation
from products.today.backend.facade.contracts import HighlightFindings
from products.today.backend.facade.testing import highlight_context

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


@time_machine.travel(NOW, tick=False)
class TestEvaluationNumber(BaseTest):
    def _evaluation(self, name: str, *, created_by: User | None = None, **fields) -> Evaluation:
        return Evaluation.objects.create(
            team=self.team,
            name=name,
            output_type="boolean",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            created_by=created_by or self.user,
            **{"enabled": True, **fields},
        )

    def _runs(self, evaluation: Evaluation, *rates: tuple[int, float | None, float | None]) -> None:
        report = EvaluationReport.objects.create(
            team=self.team, evaluation=evaluation, frequency=EvaluationReport.Frequency.EVERY_N, trigger_threshold=10
        )
        for days_ago, rate, previous in rates:
            end = NOW - timedelta(days=days_ago)
            EvaluationReportRun.objects.create(
                report=report,
                content={},
                metadata={} if rate is None else {"pass_rate": rate, "previous_pass_rate": previous},
                period_start=end - timedelta(days=1),
                period_end=end,
            )

    def _find(self, hidden: frozenset[str] = frozenset()) -> HighlightFindings:
        source = next(s for s in HIGHLIGHT_SOURCES if s.name == "evaluation_numbers")
        return source.find(highlight_context(team=self.team, user=self.user, today=NOW.date(), hidden=hidden))

    def test_the_number_is_the_latest_pass_rate_with_its_previous_report(self) -> None:
        evaluation = self._evaluation("Answer accuracy")
        self._runs(evaluation, (3, 80.0, 70.0), (2, None, None), (1, 90.0, 60.0))

        [number] = self._find().pulse

        self.assertEqual(
            (
                number.key,
                number.value,
                number.previous_value,
                round(number.change_pct or 0, 2),
                number.series,
                number.period_starts,
                number.url,
                number.reason,
            ),
            (
                f"evaluation:{evaluation.id}",
                90.0,
                80.0,
                12.5,
                [80.0, 90.0],
                [date(2026, 11, 7), date(2026, 11, 9)],
                f"/ai-evals/evaluations/{evaluation.id}",
                "evaluation",
            ),
        )

    @parameterized.expand(
        [
            ("someone else's", {"created_by": "other"}, False),
            ("a disabled one", {"enabled": False}, False),
            ("an ignored one", {}, True),
            ("one whose last report is stale", {"stale": True}, False),
        ]
    )
    def test_the_number_skips(self, _name: str, change: dict, hide: bool) -> None:
        fallback = self._evaluation("Fallback")
        self._runs(fallback, (1, 50.0, None))
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        fields = {k: v for k, v in change.items() if k not in ("created_by", "stale")}
        skipped = self._evaluation("Skipped", created_by=other if change.get("created_by") else None, **fields)
        self._runs(skipped, (40 if change.get("stale") else 1, 99.0, None))

        found = self._find(frozenset({f"evaluation:{skipped.id}"}) if hide else frozenset())

        self.assertEqual([number.key for number in found.pulse], [f"evaluation:{fallback.id}"])

    def test_only_evaluations_the_person_can_view_get_a_name(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        shown = self._evaluation("Answer accuracy")
        restricted = self._evaluation("Tone check")
        create_access_control(
            team_id=self.team.id, resource="evaluation", resource_id=str(restricted.id), access_level="none"
        )
        reader = User.objects.create_and_join(self.organization, "reader@example.com", None)

        names = today_highlights.name_evaluation_numbers(
            self.team, reader, [f"evaluation:{shown.id}", f"evaluation:{restricted.id}", "evaluation:nope", "signup"]
        )

        self.assertEqual(names, {f"evaluation:{shown.id}": "Answer accuracy"})
