from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.ai_observability.backend.backfill_candidates import BackfillScope
from products.ai_observability.backend.logic.eval_suggestions.eligibility import TemporalUnreachable
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
)
from products.ai_observability.backend.models.evaluation_backfill import EvaluationBackfill
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.event_definitions.backend.models.property_definition import PropertyDefinition

ACCEPT_MODULE = "products.ai_observability.backend.logic.eval_suggestions.accept"
SUGGESTIONS_MODULE = "products.ai_observability.backend.logic.eval_suggestions.suggestions"
BACKFILLS_MODULE = "products.ai_observability.backend.api.evaluation_backfills"

CHECK_DRAFT = {
    "name": "Turns that end on a failed call",
    "description": "Finds failed calls nobody retried",
    "evaluation_type": "hog",
    "evaluation_config": {"source": "return true"},
    "output_type": "boolean",
    "output_config": {"allows_na": True},
    "target": "trace",
}
JUDGE_DRAFT = {
    "name": "Security findings marked P0 or P1",
    "description": "Checks severe findings",
    "evaluation_type": "llm_judge",
    "evaluation_config": {"prompt": "Return true when every P0 finding deserves it."},
    "output_type": "boolean",
    "output_config": {},
    "target": "trace",
}


def _temporal_client() -> MagicMock:
    client = MagicMock()
    client.start_workflow = AsyncMock()
    return client


def _conditions(product: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "scouts",
            "rollout_percentage": 100,
            "properties": [{"key": "ai_product", "value": [product], "operator": "exact", "type": "event"}],
        }
    ]


def _evaluation(team: Team, **overrides: Any) -> Evaluation:
    fields: dict[str, Any] = {
        "name": "Scout findings cite their data",
        "evaluation_type": "hog",
        "evaluation_config": {"source": "return true"},
        "output_type": "boolean",
        "target": "trace",
        "enabled": True,
        "conditions": _conditions("signals"),
        **overrides,
    }
    evaluation = Evaluation.objects.create(team=team, **fields)
    # Last edited well before any suggestion run read it.
    Evaluation.objects.filter(pk=evaluation.pk).update(updated_at=timezone.now() - timedelta(days=10))
    evaluation.refresh_from_db()
    return evaluation


class TestEvalSuggestionsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.suggestion_run = EvalSuggestionRun.objects.for_team(self.team.pk).create(
            team=self.team, trigger="manual", status=EvalSuggestionRunStatus.COMPLETED, completed_at=timezone.now()
        )
        self.url = f"/api/projects/{self.team.id}/evaluation_suggestions"

    def _suggestion(self, kind: str = EvalSuggestionKind.NEW_HOG, **fields: Any) -> EvalSuggestion:
        defaults: dict[str, Any] = {
            "template_key": "unrecovered_errors",
            "dedupe_key": f"check:{kind}",
            "headline": "1 in 125 traces ends on a failed call",
            "reason": "A call failed and nothing retried it.",
            "draft": CHECK_DRAFT,
            "filters": [{"key": "ai_product", "value": ["chat"], "operator": "exact", "type": "event"}],
            "rollout_percentage": 100,
            "mean_input_tokens": 1000,
        }
        return EvalSuggestion.objects.for_team(self.team.pk).create(
            team=self.team, kind=kind, **{**defaults, "run": self.suggestion_run, **fields}
        )

    def _judge_key(self) -> None:
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Active key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )
        EvaluationConfig.objects.create(team=self.team, active_provider_key=key)

    @parameterized.expand(
        [
            ("code_check", EvalSuggestionKind.NEW_HOG, CHECK_DRAFT, 500),
            ("judge", EvalSuggestionKind.NEW_LLM_JUDGE, JUDGE_DRAFT, 50),
        ]
    )
    @patch(f"{BACKFILLS_MODULE}.connect_with_deadline")
    @patch(f"{ACCEPT_MODULE}.count_backfill_candidates")
    def test_accept_creates_the_evaluation_once_and_shrinks_the_backfill_to_the_cap(
        self, _name: str, kind: str, draft: dict, cap: int, count: MagicMock, connect: MagicMock
    ) -> None:
        self._judge_key()
        connect.return_value = _temporal_client()
        # The 7-day window holds 10x the cap, so the backfill shrinks it once and recounts.
        count.side_effect = [
            BackfillScope(to_evaluate=cap * 10, already_judged=0),
            BackfillScope(to_evaluate=cap - 3, already_judged=0),
        ]
        suggestion = self._suggestion(kind, draft=draft, rollout_percentage=40)

        first = self.client.post(f"{self.url}/{suggestion.id}/accept/")
        second = self.client.post(f"{self.url}/{suggestion.id}/accept/")

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.json()["evaluation_id"] == first.json()["evaluation_id"]
        assert second.json()["backfill_id"] == first.json()["backfill_id"]
        assert first.json()["backfill_units"] == cap - 3
        evaluation = Evaluation.objects.get(team=self.team)
        assert evaluation.enabled and evaluation.name == draft["name"]
        assert evaluation.conditions[0]["rollout_percentage"] == 40
        assert evaluation.conditions[0]["properties"] == suggestion.filters

        first_window, shrunk_window = (call.kwargs for call in count.call_args_list)
        assert shrunk_window["window_end"] == first_window["window_end"]
        assert shrunk_window["window_start"] > first_window["window_start"] + timedelta(days=5)
        backfill = EvaluationBackfill.objects.for_team(self.team.pk).get(evaluation=evaluation)
        assert backfill.window_start == shrunk_window["window_start"]
        # Units that land in the window after the count must not take the walk past it.
        assert backfill.max_units == cap - 3
        assert connect.return_value.start_workflow.await_count == 1
        suggestion.refresh_from_db()
        assert suggestion.status == EvalSuggestionStatus.ACCEPTED and suggestion.created_evaluation == evaluation

    @parameterized.expand(
        [
            (
                "judge_without_a_working_key",
                EvalSuggestionKind.NEW_LLM_JUDGE,
                EvalSuggestionStatus.PROPOSED,
                "provider API key",
            ),
            ("dismissed", EvalSuggestionKind.NEW_HOG, EvalSuggestionStatus.DISMISSED, "no longer open"),
            (
                "accepted_then_deleted",
                EvalSuggestionKind.NEW_HOG,
                EvalSuggestionStatus.ACCEPTED,
                "no longer open",
            ),
        ]
    )
    def test_refused_accept_creates_nothing(self, _name: str, kind: str, suggestion_status: str, message: str) -> None:
        accepted = suggestion_status == EvalSuggestionStatus.ACCEPTED
        suggestion = self._suggestion(
            kind,
            draft=JUDGE_DRAFT if kind == EvalSuggestionKind.NEW_LLM_JUDGE else CHECK_DRAFT,
            status=suggestion_status,
            created_evaluation=_evaluation(self.team, deleted=True) if accepted else None,
        )

        response = self.client.post(f"{self.url}/{suggestion.id}/accept/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
        assert not Evaluation.objects.filter(team=self.team, deleted=False).exists()

    @parameterized.expand(
        [
            ("applies_the_fix", EvalSuggestionStatus.PROPOSED, False, status.HTTP_200_OK, "signals_scout"),
            (
                "evaluation_edited_after_the_run",
                EvalSuggestionStatus.PROPOSED,
                True,
                status.HTTP_409_CONFLICT,
                "edited",
            ),
            ("dismissed", EvalSuggestionStatus.DISMISSED, False, status.HTTP_400_BAD_REQUEST, "signals"),
            ("expired", EvalSuggestionStatus.EXPIRED, False, status.HTTP_400_BAD_REQUEST, "signals"),
        ]
    )
    def test_apply_fix(
        self, _name: str, suggestion_status: str, edited: bool, expected_status: int, expected_product: str
    ) -> None:
        target = _evaluation(self.team)
        suggestion = self._suggestion(
            EvalSuggestionKind.FIX_EVAL,
            status=suggestion_status,
            draft={"conditions": _conditions("signals_scout")},
            target_evaluation=target,
        )
        if edited:
            target.conditions = _conditions("edited")
            target.save()

        response = self.client.post(f"{self.url}/{suggestion.id}/apply_fix/")

        assert response.status_code == expected_status, response.json()
        target.refresh_from_db()
        assert target.conditions[0]["properties"][0]["value"] == [expected_product]

    @parameterized.expand(
        [
            ("open", EvalSuggestionStatus.PROPOSED, False, True),
            ("applied", EvalSuggestionStatus.ACCEPTED, False, False),
            ("evaluation_edited_after_the_run", EvalSuggestionStatus.PROPOSED, True, False),
        ]
    )
    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_list_shows_only_fixes_that_still_apply(
        self, _name: str, suggestion_status: str, edited: bool, listed: bool, _flag: MagicMock
    ) -> None:
        target = _evaluation(self.team)
        fix = self._suggestion(
            EvalSuggestionKind.FIX_EVAL,
            status=suggestion_status,
            draft={"conditions": _conditions("signals_scout")},
            target_evaluation=target,
        )
        if edited:
            target.save()

        results = self.client.get(f"{self.url}/").json()["results"]

        assert [row["id"] for row in results] == ([str(fix.id)] if listed else [])

    @parameterized.expand([("with_reason", {"reason": "too_noisy"}, "too_noisy"), ("without_reason", {}, None)])
    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_dismiss_hides_the_suggestion(self, _name: str, body: dict, reason: str | None, _flag: MagicMock) -> None:
        suggestion = self._suggestion()
        kept = self._suggestion(dedupe_key="check:other")

        response = self.client.post(f"{self.url}/{suggestion.id}/dismiss/", body, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        suggestion.refresh_from_db()
        assert suggestion.status == EvalSuggestionStatus.DISMISSED and suggestion.dismiss_reason == reason
        listed = self.client.get(f"{self.url}/").json()
        assert [row["id"] for row in listed["results"]] == [str(kept.id)]

    def test_dismiss_rejects_an_unknown_reason(self) -> None:
        response = self.client.post(f"{self.url}/{self._suggestion().id}/dismiss/", {"reason": "boring"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("burst_then_an_empty_slice", [5000, 0], 0, 10),
            ("still_too_full_after_every_shrink", [5000, 4000, 3000, 2000], 3, 10),
            # A second count would raise, as the side effects run out.
            ("counts_use_up_the_budget", [5000], 0, -1),
        ]
    )
    @patch(f"{BACKFILLS_MODULE}.connect_with_deadline")
    @patch(f"{ACCEPT_MODULE}.count_backfill_candidates")
    def test_accept_falls_back_to_the_last_window_with_traffic(
        self, _name: str, counts: list[int], kept_window: int, budget: int, count: MagicMock, connect: MagicMock
    ) -> None:
        connect.return_value = _temporal_client()
        count.side_effect = [BackfillScope(to_evaluate=units, already_judged=0) for units in counts]

        with patch(f"{ACCEPT_MODULE}.PLAN_BUDGET_SECONDS", budget):
            response = self.client.post(f"{self.url}/{self._suggestion().id}/accept/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        backfill = EvaluationBackfill.objects.for_team(self.team.pk).get()
        assert backfill.max_units == 500
        assert backfill.window_start == count.call_args_list[kept_window].kwargs["window_start"]

    @patch(f"{ACCEPT_MODULE}.count_backfill_candidates", side_effect=RuntimeError("Code: 159. Timeout exceeded"))
    def test_accept_keeps_the_evaluation_when_the_backfill_cannot_start(self, _count: MagicMock) -> None:
        response = self.client.post(f"{self.url}/{self._suggestion().id}/accept/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["backfill_id"] is None
        assert Evaluation.objects.filter(team=self.team, deleted=False).count() == 1

    @parameterized.expand([("with_a_working_key", True, "gpt-5-mini", 0.2), ("without_a_key", False, None, None)])
    @patch(f"{ACCEPT_MODULE}.count_backfill_candidates", return_value=BackfillScope(to_evaluate=20, already_judged=0))
    def test_judge_estimate_prices_whole_units_on_the_key_accept_uses(
        self, _name: str, with_key: bool, model: str | None, cost: float | None, _count: MagicMock
    ) -> None:
        if with_key:
            self._judge_key()
        # One trace judge run reads a 40k-token transcript, at $0.25 per million input tokens.
        suggestion = self._suggestion(EvalSuggestionKind.NEW_LLM_JUDGE, draft=JUDGE_DRAFT, mean_input_tokens=40_000)

        estimate = self.client.get(f"{self.url}/{suggestion.id}/accept_estimate/").json()

        assert (estimate["units"], estimate["judge_model"]) == (20, model)
        assert estimate["estimated_cost_usd"] == (None if cost is None else pytest.approx(cost))

    @parameterized.expand([("untouched", False, True), ("edited_after_the_run", True, False)])
    def test_retrieve_says_whether_a_fix_still_applies(self, _name: str, edited: bool, applies: bool) -> None:
        target = _evaluation(self.team)
        fix = self._suggestion(
            EvalSuggestionKind.FIX_EVAL, draft={"conditions": _conditions("signals_scout")}, target_evaluation=target
        )
        if edited:
            target.save()

        assert self.client.get(f"{self.url}/{fix.id}/").json()["applies"] is applies

    @patch("products.ai_observability.backend.api.evaluations.report_user_action")
    def test_applied_fix_is_tracked_as_an_evaluation_update(self, report: MagicMock) -> None:
        target = _evaluation(self.team)
        fix = self._suggestion(
            EvalSuggestionKind.FIX_EVAL, draft={"conditions": _conditions("signals_scout")}, target_evaluation=target
        )

        self.client.post(f"{self.url}/{fix.id}/apply_fix/")

        updated = [call for call in report.call_args_list if call.args[1] == "llma evaluation updated"]
        assert [call.args[2]["suggestion_id"] for call in updated] == [str(fix.id)]
        assert updated[0].args[2]["changed_fields"] == ["conditions"]

    @parameterized.expand(
        [
            ("starts", None, True, True),
            ("temporal_unreachable", TemporalUnreachable("connection refused"), False, False),
            # The start may have reached Temporal, so the run stays and reads as pending.
            ("start_outcome_unknown", RuntimeError("deadline exceeded"), True, True),
        ]
    )
    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_first_visit_starts_one_run_a_day(
        self, _name: str, start_error: Exception | None, first_pending: bool, later_pending: bool, _flag: MagicMock
    ) -> None:
        self.suggestion_run.delete()
        with patch(
            "products.ai_observability.backend.facade.eval_suggestions.start_first_visit_run",
            new=AsyncMock(side_effect=start_error),
        ) as start:
            first = self.client.get(f"{self.url}/").json()
            second = self.client.get(f"{self.url}/").json()

        assert (first["pending"], second["pending"]) == (first_pending, later_pending)
        assert start.await_count == 1

    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_dismissing_a_card_also_dismisses_its_replacement(self, _flag: MagicMock) -> None:
        # A run published the replacement while the dismissal of the older card waited on its lock.
        older = self._suggestion(status=EvalSuggestionStatus.EXPIRED)
        newer_run = EvalSuggestionRun.objects.for_team(self.team.pk).create(
            team=self.team, trigger="manual", status=EvalSuggestionRunStatus.COMPLETED, completed_at=timezone.now()
        )
        replacement = self._suggestion(run=newer_run)

        self.client.post(f"{self.url}/{older.id}/dismiss/", {"reason": "too_noisy"}, format="json")

        replacement.refresh_from_db()
        assert replacement.status == EvalSuggestionStatus.DISMISSED
        assert self.client.get(f"{self.url}/").json()["results"] == []

    @parameterized.expand(
        [
            ("read_without_query", "get", "", ["evaluation:read"], status.HTTP_403_FORBIDDEN),
            ("read_with_query", "get", "", ["evaluation:read", "query:read"], status.HTTP_200_OK),
            ("write_without_query", "post", "dismiss/", ["evaluation:write"], status.HTTP_403_FORBIDDEN),
            ("write_with_query", "post", "dismiss/", ["evaluation:write", "query:read"], status.HTTP_200_OK),
        ]
    )
    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_api_key_needs_query_read_for_trace_evidence(
        self, _name: str, method: str, path: str, scopes: list[str], expected: int, _flag: MagicMock
    ) -> None:
        suggestion = self._suggestion()
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = getattr(self.client, method)(f"{self.url}/{suggestion.id}/{path}", format="json")

        assert response.status_code == expected, response.json()


class TestEvalSuggestionsAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.member = User.objects.create_and_join(self.organization, "suggestions-member@posthog.com", "testtest")
        self.suggestion_run = EvalSuggestionRun.objects.for_team(self.team.pk).create(
            team=self.team, trigger="manual", status=EvalSuggestionRunStatus.COMPLETED, completed_at=timezone.now()
        )

    def _grant(self, access_level: str, evaluation: Evaluation | None = None) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=str(evaluation.id) if evaluation else None,
            access_level=access_level,
            organization_member=OrganizationMembership.objects.get(user=self.member, organization=self.organization),
        )

    @parameterized.expand(
        [
            ("accept_with_access_to_one_other_evaluation", "none", False, EvalSuggestionKind.NEW_HOG, "accept"),
            ("fix_of_an_evaluation_the_member_cannot_edit", "editor", True, EvalSuggestionKind.FIX_EVAL, "apply_fix"),
        ]
    )
    def test_member_without_edit_access_changes_nothing(
        self, _name: str, resource_level: str, grant_on_target: bool, kind: str, action: str
    ) -> None:
        target = _evaluation(self.team)
        other = _evaluation(self.team, name="Another evaluation")
        self._grant(resource_level)
        if grant_on_target:
            self._grant("viewer", target)
        else:
            self._grant("editor", other)
        suggestion = EvalSuggestion.objects.for_team(self.team.pk).create(
            team=self.team,
            run=self.suggestion_run,
            kind=kind,
            dedupe_key=f"{kind}:one",
            headline="Suggestion",
            reason="Reason",
            draft={"conditions": _conditions("signals_scout")} if kind == EvalSuggestionKind.FIX_EVAL else CHECK_DRAFT,
            target_evaluation=target if kind == EvalSuggestionKind.FIX_EVAL else None,
        )
        self.client.force_login(self.member)

        response = self.client.post(f"/api/projects/{self.team.id}/evaluation_suggestions/{suggestion.id}/{action}/")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert Evaluation.objects.filter(team=self.team).count() == 2
        target.refresh_from_db()
        assert target.conditions[0]["properties"][0]["value"] == ["signals"]

    @parameterized.expand([("target_evaluation",), ("similar_evaluation",)])
    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_member_sees_no_suggestion_naming_an_evaluation_hidden_from_them(
        self, field: str, _flag: MagicMock
    ) -> None:
        hidden = _evaluation(self.team, name="Hidden evaluation")
        self._grant("editor")
        self._grant("none", hidden)
        suggestion = EvalSuggestion.objects.for_team(self.team.pk).create(
            team=self.team,
            run=self.suggestion_run,
            kind=EvalSuggestionKind.FIX_EVAL if field == "target_evaluation" else EvalSuggestionKind.NEW_HOG,
            dedupe_key="hidden:one",
            headline="Suggestion",
            reason="Reason",
            draft=CHECK_DRAFT,
            **{field: hidden},
        )
        self.client.force_login(self.member)
        url = f"/api/projects/{self.team.id}/evaluation_suggestions"

        assert self.client.get(f"{url}/").json()["results"] == []
        assert self.client.get(f"{url}/{suggestion.id}/").status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_dismissal_leaves_a_replacement_that_names_a_hidden_evaluation(self, _flag: MagicMock) -> None:
        hidden = _evaluation(self.team, name="Hidden evaluation")
        self._grant("editor")
        self._grant("none", hidden)
        newer_run = EvalSuggestionRun.objects.for_team(self.team.pk).create(
            team=self.team, trigger="manual", status=EvalSuggestionRunStatus.COMPLETED, completed_at=timezone.now()
        )
        cards = [
            EvalSuggestion.objects.for_team(self.team.pk).create(
                team=self.team,
                run=run,
                kind=EvalSuggestionKind.NEW_HOG,
                dedupe_key="same:card",
                headline="Suggestion",
                reason="Reason",
                draft=CHECK_DRAFT,
                similar_evaluation=similar,
            )
            for run, similar in ((self.suggestion_run, None), (newer_run, hidden))
        ]
        self.client.force_login(self.member)

        response = self.client.post(
            f"/api/projects/{self.team.id}/evaluation_suggestions/{cards[0].id}/dismiss/", {}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        cards[1].refresh_from_db()
        assert cards[1].status == EvalSuggestionStatus.PROPOSED

    @patch(f"{SUGGESTIONS_MODULE}.is_enabled_for_organization", return_value=True)
    def test_member_with_a_hidden_event_property_sees_no_suggestions(self, _flag: MagicMock) -> None:
        self.organization.available_product_features = [
            *(self.organization.available_product_features or []),
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL},
        ]
        self.organization.save()
        self._grant("editor")
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=PropertyDefinition.objects.create(
                team=self.team, name="ai_product", property_type="String", type=PropertyDefinition.Type.EVENT
            ),
            organization_member=OrganizationMembership.objects.get(user=self.member, organization=self.organization),
            access_level=PropertyAccessLevel.NONE.value,
        )
        suggestion = EvalSuggestion.objects.for_team(self.team.pk).create(
            team=self.team,
            run=self.suggestion_run,
            kind=EvalSuggestionKind.NEW_HOG,
            dedupe_key="segment:one",
            headline="1 in 40 chat traces ends on a failed call",
            reason="Reason",
            draft=CHECK_DRAFT,
            filters=[{"key": "ai_product", "value": ["chat"], "operator": "exact", "type": "event"}],
        )
        self.client.force_login(self.member)
        url = f"/api/projects/{self.team.id}/evaluation_suggestions"

        assert self.client.get(f"{url}/").json()["results"] == []
        assert self.client.get(f"{url}/{suggestion.id}/accept_estimate/").status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{ACCEPT_MODULE}.count_backfill_candidates", return_value=BackfillScope(to_evaluate=0, already_judged=0))
    def test_member_loses_an_accepted_suggestion_once_its_evaluation_is_hidden(self, _count: MagicMock) -> None:
        self._grant("editor")
        suggestion = EvalSuggestion.objects.for_team(self.team.pk).create(
            team=self.team,
            run=self.suggestion_run,
            kind=EvalSuggestionKind.NEW_HOG,
            dedupe_key="check:one",
            headline="Suggestion",
            reason="Reason",
            draft=CHECK_DRAFT,
        )
        url = f"/api/projects/{self.team.id}/evaluation_suggestions/{suggestion.id}/accept/"
        created = Evaluation.objects.get(id=self.client.post(url).json()["evaluation_id"])
        self._grant("none", created)
        self.client.force_login(self.member)

        assert self.client.get(url.removesuffix("accept/")).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.post(url).status_code == status.HTTP_404_NOT_FOUND
