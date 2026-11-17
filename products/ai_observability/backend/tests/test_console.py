import re
import uuid

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.utils import timezone

from parameterized import parameterized

from posthog.models.user import User

from products.ai_observability.backend.facade.admin import MigrationAction, migrate_taggers
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionReviewVerdict,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
)
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.ai_observability.backend.models.taggers import Tagger


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
                outcome=f"Checks the {key} rule.",
                reason=f"Measured the {key} rule.",
                evidence=[{"trace_id": "trace/1?step=2#end%2F", "reason": "Example reason"}],
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
        assert "Checks the check:b rule." in content and "Measured the check:b rule." in content
        assert "/ai-observability/traces/trace%252F1%253Fstep%253D2%2523end%25252F" in content
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
        assert "Checks the check:a rule." in content and "Measured the check:a rule." in content


class TestTaggersPanel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.customer = User.objects.create_and_join(self.organization, "customer@example.com", None)
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Customer key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
        )
        EvaluationConfig.objects.create(team=self.team, active_provider_key=key)
        llm_config = {"prompt": "What does the user want?", "tags": [{"name": "Billing issue"}, {"name": "Other"}]}
        self.active = Tagger.objects.create(
            team=self.team,
            name="User intent",
            enabled=True,
            tagger_config={**llm_config, "max_tags": 1},
            conditions=[{"id": "all", "rollout_percentage": 25, "properties": []}],
            created_by=self.customer,
        )
        self.silent = Tagger.objects.create(team=self.team, name="Sentiment", enabled=True, tagger_config=llm_config)
        self.untagged_hog = Tagger.objects.create(
            team=self.team,
            name="Free-form Hog",
            enabled=True,
            tagger_type="hog",
            tagger_config={"source": "return ['anything']"},
        )
        self.hog = Tagger.objects.create(
            team=self.team,
            name="Long answers",
            enabled=True,
            tagger_type="hog",
            tagger_config={"source": "return length(output) > 10 ? ['Long'] : []", "tags": [{"name": "Long"}]},
        )
        self.legacy = Tagger.objects.create(team=self.team, name="Legacy", enabled=True, tagger_config=llm_config)
        Tagger.objects.filter(pk=self.legacy.pk).update(tagger_config={**llm_config, "prompt": ""})
        self.url = f"/admin/console/teams/{self.team.pk}/ai-observability-taggers/migrate-taggers/"

    @patch("products.ai_observability.backend.logic.tagger_migration.migration.reload_taggers_on_workers")
    @patch("products.ai_observability.backend.logic.tagger_migration.migration.load_recent_tag_counts")
    def test_migrating_moves_active_taggers_to_evaluations_and_switches_off_silent_ones(
        self, load_counts: MagicMock, reload_taggers: MagicMock
    ) -> None:
        load_counts.return_value = {
            str(self.active.id): 120,
            str(self.untagged_hog.id): 40,
            str(self.hog.id): 7,
            str(self.legacy.id): 3,
        }

        preview = self.client.post(self.url, {"reason": "Taggers are deprecated"})
        assert preview.status_code == 200
        assert Evaluation.objects.filter(team=self.team).count() == 0
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, {"confirm_token": preview.context["confirm_token"]})
            second_run = migrate_taggers(self.team)

        assert response.status_code == 302
        evaluation = Evaluation.objects.get(team=self.team, evaluation_type="llm_judge")
        hog_evaluation = Evaluation.objects.get(team=self.team, evaluation_type="hog")
        assert hog_evaluation.enabled
        assert hog_evaluation.created_by is None
        assert hog_evaluation.output_config["options"] == [{"key": "long", "label": "Long"}]
        assert hog_evaluation.evaluation_config["bytecode"]
        assert (evaluation.name, evaluation.enabled, evaluation.output_type, evaluation.created_by) == (
            "User intent",
            True,
            "categorical",
            self.customer,
        )
        assert evaluation.output_config["selection_mode"] == "single"
        assert evaluation.output_config["allows_na"] is True
        assert [option["key"] for option in evaluation.output_config["options"]] == ["billing_issue", "other"]
        assert evaluation.conditions[0]["rollout_percentage"] == 25
        assert evaluation.model_configuration is not None and evaluation.model_configuration.provider == "openai"
        states = {
            tagger.name: (tagger.enabled, tagger.migrated_to_evaluation_id)
            for tagger in Tagger.objects.filter(team=self.team)
        }
        assert states == {
            "User intent": (False, evaluation.id),
            "Sentiment": (False, None),
            "Free-form Hog": (True, None),
            "Long answers": (False, hog_evaluation.id),
            "Legacy": (True, None),
        }
        assert sorted(call.kwargs["tagger_ids"][0] for call in reload_taggers.call_args_list) == sorted(
            [str(self.active.id), str(self.silent.id), str(self.hog.id)]
        )
        assert [step.action for step in second_run] == [MigrationAction.SKIP, MigrationAction.SKIP]
