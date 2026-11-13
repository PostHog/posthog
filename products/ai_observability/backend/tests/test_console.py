import re
import uuid

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.utils import timezone

from parameterized import parameterized

from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionReviewVerdict,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
)


class TestAIObservabilityConsoleTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    @parameterized.expand(
        [
            ("queued", "2026-07-15", None, 302, True),
            (
                "refused_by_the_command",
                "2026-07-15",
                CommandError("A run for 2026-07-15 was already dispatched."),
                400,
                True,
            ),
            ("date_too_far_ahead", "2026-07-30", None, 400, False),
        ]
    )
    @patch("products.ai_observability.backend.admin.call_command")
    @time_machine.travel("2026-07-22T12:00:00Z", tick=False)
    def test_sending_the_ai_observability_usage_report_queues_it_or_shows_why_not(
        self,
        _name: str,
        report_date: str,
        command_error: Exception | None,
        expected_status: int,
        expect_called: bool,
        call_command: MagicMock,
    ) -> None:
        call_command.side_effect = command_error

        response = self.client.post(
            "/admin/console/tools/ai-observability/send-usage-report/", {"report_date": report_date}
        )

        assert response.status_code == expected_status
        assert call_command.called == expect_called
        if expect_called:
            call_command.assert_called_once_with(
                "send_ai_observability_usage_report", f"--date={report_date}", "--async"
            )
        if command_error is not None:
            assert "already dispatched" in response.content.decode()


class TestEvalSuggestionReviewTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        run = EvalSuggestionRun.objects.for_team(self.team.pk).create(
            team=self.team, trigger="manual", status=EvalSuggestionRunStatus.COMPLETED, completed_at=timezone.now()
        )
        self.labeled, self.unlabeled = (
            EvalSuggestion.objects.for_team(self.team.pk).create(
                team=self.team,
                run=run,
                kind=EvalSuggestionKind.NEW_HOG,
                dedupe_key=key,
                headline=headline,
                outcome="Outcome",
                reason="Reason",
                evidence=[{"trace_id": "trace-1", "reason": "Example reason"}],
                review_verdict=verdict,
            )
            for key, headline, verdict in (
                ("check:a", "Already labeled card", EvalSuggestionReviewVerdict.BAD),
                ("check:b", "Card waiting for a label", None),
            )
        )

    @parameterized.expand([("all_cards", "", True), ("only_unlabeled", "?unlabeled=on", False)])
    def test_page_lists_published_cards(self, _name: str, query: str, shows_labeled: bool) -> None:
        response = self.client.get(f"/admin/console/tools/eval-suggestion-review/{query}")

        assert response.status_code == 200
        content = response.content.decode()
        assert "Card waiting for a label" in content
        assert ("Already labeled card" in content) is shows_labeled

    @parameterized.expand([("known_card", True, 302), ("unknown_card", False, 404)])
    def test_labeling_saves_the_verdict_and_note(self, _name: str, known: bool, expected_status: int) -> None:
        suggestion_id = self.unlabeled.id if known else uuid.uuid4()

        response = self.client.post(
            "/admin/console/tools/eval-suggestion-review/label/",
            {"team": self.team.pk, "suggestion": str(suggestion_id), "verdict": "good", "note": "Real failures"},
        )

        assert response.status_code == expected_status
        self.unlabeled.refresh_from_db()
        assert (self.unlabeled.review_verdict, self.unlabeled.review_note, self.unlabeled.reviewed_by_id) == (
            ("good", "Real failures", self.user.pk) if known else (None, "", None)
        )

    def test_the_label_form_opens_with_the_cards_current_label(self) -> None:
        self.labeled.review_note = "Examples are summaries"
        self.labeled.save()

        response = self.client.get(
            f"/admin/console/tools/eval-suggestion-review/label/?team={self.team.pk}&suggestion={self.labeled.id}"
        )

        content = response.content.decode()
        assert re.search(r'<option value="bad"\s+selected>', content)
        assert "Examples are summaries" in content
