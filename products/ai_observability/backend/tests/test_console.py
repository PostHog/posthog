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

from posthog.models.user import User

from products.access_control.backend.facade.api import replace_object_access_rules
from products.access_control.backend.facade.contracts import ObjectAccessRuleInput
from products.access_control.backend.facade.testing import create_access_control
from products.ai_observability.backend.facade.admin import MigrationAction, migrate_taggers, plan_tagger_migration
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionReviewVerdict,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
)
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.model_configuration import LLMModelConfiguration
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
        assert re.findall(r'data-slot="card-title">([^<]*)</h2>', content)[0] == headline
        assert (headline == "Already labeled card") is ("Card waiting for a label" not in content)
        assert f"Checks the {key} rule." in content and f"Measured the {key} rule." in content
        assert "/ai-observability/traces/trace%252F1%253Fstep%253D2%2523end%25252F" in content
        form = re.search(r'action="/admin/console/tools/eval-suggestion-review/label/\?([^"]*)"', content)
        assert form is not None and dict(parse_qsl(html.unescape(form.group(1)))) == after_label
        assert 'data-console-key="ArrowRight"' in content and 'data-console-key="ArrowLeft"' in content
        # Staff label from the card, so the page has no form that asks for a suggestion ID.
        assert "tool-actions-title" not in content

    def test_the_labeled_cards_list_every_label_and_open_each_card(self) -> None:
        content = self.client.get("/admin/console/tools/eval-suggestion-review/").content.decode()

        link = f"/admin/console/tools/eval-suggestion-review/?days=30&amp;suggestion={self.labeled.id}"
        assert link in content and "Examples are summaries" in content
        opened = self.client.get(link.replace("&amp;", "&")).content.decode()
        assert re.findall(r'data-slot="card-title">([^<]*)</h2>', opened)[0] == "Already labeled card"
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

    def test_a_named_card_outside_the_loaded_cards_says_so(self) -> None:
        with patch("products.ai_observability.backend.logic.eval_suggestions.review_queries.MAX_REVIEW_CARDS", 1):
            response = self.client.get(
                f"/admin/console/tools/eval-suggestion-review/?days=30&suggestion={self.unlabeled.id}"
            )

        content = response.content.decode()
        assert "That card is not among the 1 newest cards" in content
        assert re.findall(r'data-slot="card-title">([^<]*)</h2>', content)[0] == "Already labeled card"


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
        broken_key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Revoked key",
            state=LLMProviderKey.State.ERROR,
            encrypted_config={"api_key": "sk-revoked"},
        )
        self.broken_key = Tagger.objects.create(
            team=self.team,
            name="On a broken key",
            enabled=True,
            tagger_config=llm_config,
            model_configuration=LLMModelConfiguration.objects.create(
                team=self.team, provider="openai", model="gpt-5-mini", provider_key=broken_key
            ),
        )
        self.private = Tagger.objects.create(team=self.team, name="Private", enabled=True, tagger_config=llm_config)
        replace_object_access_rules(
            team_id=self.team.pk,
            resource="tagger",
            resource_id=str(self.private.id),
            rules=[ObjectAccessRuleInput(access_level="none")],
        )
        self.bounded = Tagger.objects.create(
            team=self.team,
            name="Bounded",
            enabled=True,
            tagger_config={**llm_config, "tags": [*llm_config["tags"], {"name": "Bug"}], "max_tags": 2},
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
            str(self.broken_key.id): 5,
            str(self.private.id): 9,
            str(self.bounded.id): 11,
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
        assert [option["key"] for option in evaluation.output_config["options"]] == ["billing-issue", "other"]
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
            "On a broken key": (True, None),
            "Private": (True, None),
            "Bounded": (True, None),
        }
        assert sorted(call.kwargs["tagger_ids"][0] for call in reload_taggers.call_args_list) == sorted(
            [str(self.active.id), str(self.silent.id), str(self.hog.id)]
        )
        assert [step.action for step in second_run] == [MigrationAction.SKIP] * 5

    @parameterized.expand(
        [
            ("tagger_rule_only", ["tagger"], MigrationAction.SKIP),
            ("same_rule_on_both", ["tagger", "evaluation"], MigrationAction.MIGRATE),
        ]
    )
    @patch("products.ai_observability.backend.logic.tagger_migration.migration.load_recent_tag_counts")
    def test_team_wide_access_rules_must_match_before_a_tagger_moves(
        self, _name: str, resources: list[str], expected: MigrationAction, load_counts: MagicMock
    ) -> None:
        load_counts.return_value = {str(self.active.id): 120}
        for resource in resources:
            create_access_control(team_id=self.team.pk, resource=resource, access_level="viewer")

        steps = {step.tagger_name: step.action for step in plan_tagger_migration(self.team)}

        assert steps["User intent"] == expected
