import re
import html
import uuid
from urllib.parse import parse_qsl

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team

from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionReviewVerdict,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
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


def _first_card(content: str) -> str:
    """The title of the first card on the review page, after the tool's Actions card."""
    return next(title for title in re.findall(r'data-slot="card-title">([^<]*)</h2>', content) if title != "Actions")


class TestEvalSuggestionReviewTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        run = EvalSuggestionRun.objects.for_team(self.team.pk).create(
            team=self.team, trigger="manual", status=EvalSuggestionRunStatus.COMPLETED, completed_at=timezone.now()
        )
        # The higher score comes first.
        self.labeled, self.unlabeled = (
            EvalSuggestion.objects.for_team(self.team.pk).create(
                team=self.team,
                run=run,
                kind=EvalSuggestionKind.NEW_HOG,
                dedupe_key=key,
                headline=headline,
                outcome=f"Checks the {key} rule.",
                reason=f"Measured the {key} rule.",
                evidence=[{"trace_id": "trace/1?step=2#end%2F", "reason": "Example reason"}],
                review_verdict=verdict,
                review_note=note,
                score=score,
            )
            for key, headline, verdict, note, score in (
                ("check:a", "Already labeled card", EvalSuggestionReviewVerdict.BAD, "Examples are summaries", 2.0),
                ("check:b", "Card waiting for a label", None, "", 1.0),
            )
        )

    @parameterized.expand(
        [
            # The first visit shows only unlabeled cards, and a label leaves the next one in the same place.
            ("first_visit", "", "check:b", "Card waiting for a label", {"days": "30", "unlabeled": "on", "card": "1"}),
            ("every_card", "?days=30", "check:a", "Already labeled card", {"days": "30", "card": "2"}),
        ]
    )
    def test_the_page_shows_one_card_with_buttons_that_label_it(
        self, _name: str, query: str, key: str, headline: str, after_label: dict[str, str]
    ) -> None:
        response = self.client.get(f"/admin/console/tools/eval-suggestion-review/{query}")

        assert response.status_code == 200
        content = response.content.decode()
        assert _first_card(content) == headline
        assert (headline == "Already labeled card") is ("Card waiting for a label" not in content)
        assert f"Checks the {key} rule." in content and f"Measured the {key} rule." in content
        assert "/ai-observability/traces/trace%252F1%253Fstep%253D2%2523end%25252F" in content
        form = re.search(r'action="/admin/console/tools/eval-suggestion-review/label/\?([^"]*)"', content)
        assert form is not None and dict(parse_qsl(html.unescape(form.group(1)))) == after_label
        assert 'data-console-key="ArrowRight"' in content and 'data-console-key="ArrowLeft"' in content
        # Staff label from the card, so the page offers no label form that asks for a suggestion ID.
        assert 'href="/admin/console/tools/eval-suggestion-review/label/' not in content
        assert 'href="/admin/console/tools/eval-suggestion-review/delete-unlabeled-cards/' in content

    def test_the_labeled_cards_list_every_label_and_open_each_card(self) -> None:
        content = self.client.get("/admin/console/tools/eval-suggestion-review/").content.decode()

        link = f"/admin/console/tools/eval-suggestion-review/?days=30&amp;suggestion={self.labeled.id}"
        assert link in content and "Examples are summaries" in content
        opened = self.client.get(link.replace("&amp;", "&")).content.decode()
        assert _first_card(opened) == "Already labeled card"
        assert "Examples are summaries" in opened

    @parameterized.expand([("known_card", True, 302), ("unknown_card", False, 404)])
    def test_labeling_saves_the_verdict_and_note(self, _name: str, known: bool, expected_status: int) -> None:
        suggestion_id = self.unlabeled.id if known else uuid.uuid4()

        response = self.client.post(
            "/admin/console/tools/eval-suggestion-review/label/?days=30&card=2",
            {"team": self.team.pk, "suggestion": str(suggestion_id), "verdict": "good", "note": "Real failures"},
        )

        assert response.status_code == expected_status
        if known:
            assert response["Location"] == "/admin/console/tools/eval-suggestion-review/?days=30&card=2"
        self.unlabeled.refresh_from_db()
        assert (self.unlabeled.review_verdict, self.unlabeled.review_note, self.unlabeled.reviewed_by_id) == (
            ("good", "Real failures", self.user.pk) if known else (None, "", None)
        )

    def test_an_old_label_link_opens_the_form_for_its_card_with_its_label(self) -> None:
        response = self.client.get(
            f"/admin/console/tools/eval-suggestion-review/label/?team={self.team.pk}&suggestion={self.labeled.id}"
        )

        content = response.content.decode()
        assert re.search(rf'name="suggestion"\s+value="{self.labeled.id}"', content)
        assert re.search(rf'name="team"\s+value="{self.team.pk}"', content)
        # Saving the form unchanged keeps the card's label.
        assert re.search(r'<option value="bad"\s+selected>', content) and "Examples are summaries" in content

    def test_deleting_unlabeled_cards_keeps_labeled_accepted_and_dismissed_ones(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        run = EvalSuggestionRun.objects.for_team(other_team.pk).create(team=other_team, trigger="weekly")
        kept = {self.labeled.id}
        for key, status in (
            ("check:accepted", EvalSuggestionStatus.ACCEPTED),
            ("check:dismissed", EvalSuggestionStatus.DISMISSED),
            ("check:expired", EvalSuggestionStatus.EXPIRED),
            ("check:proposed", EvalSuggestionStatus.PROPOSED),
        ):
            card = EvalSuggestion.objects.for_team(other_team.pk).create(
                team=other_team, run=run, kind=EvalSuggestionKind.NEW_HOG, dedupe_key=key, status=status, score=1.0
            )
            if status in (EvalSuggestionStatus.ACCEPTED, EvalSuggestionStatus.DISMISSED):
                kept.add(card.id)
        url = "/admin/console/tools/eval-suggestion-review/delete-unlabeled-cards/"

        preview = self.client.post(url, {"reason": "Cards revamped"})
        assert preview.status_code == 200
        assert EvalSuggestion.objects.unscoped().count() == 6
        response = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert response.status_code == 302
        assert set(EvalSuggestion.objects.unscoped().values_list("id", flat=True)) == kept

    def test_a_named_card_outside_the_loaded_cards_says_so(self) -> None:
        with patch("products.ai_observability.backend.logic.eval_suggestions.review_queries.MAX_REVIEW_CARDS", 1):
            response = self.client.get(
                f"/admin/console/tools/eval-suggestion-review/?days=30&suggestion={self.unlabeled.id}"
            )

        content = response.content.decode()
        assert "That card is not among the 1 newest cards" in content
        assert _first_card(content) == "Already labeled card"
