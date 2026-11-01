import time
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.integrations import IntegrationManager, IntegrationPatch, observability, register_source_kinds, usages
from posthog.integrations.accessors import IntegrationReader, OAuthAccessor
from posthog.integrations.contracts import IntegrationInUse, IntegrationNotFound, IntegrationUsage
from posthog.integrations.enums import AuthType
from posthog.models import Team
from posthog.models.integration import ANY, Integration
from posthog.models.integration.oauth import OauthIntegration

OPERATIONS = "integrations_sdk_operations_total"
DURATION_COUNT = "integrations_sdk_operation_duration_seconds_count"
ROWS_RETURNED_SUM = "integrations_sdk_rows_returned_sum"
ROWS_WRITTEN = "integrations_sdk_rows_written_total"
TOKEN_REFRESH = "integrations_sdk_token_refresh_total"


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _counts(operation: str, accessor: str, kind: str, auth_type: str, outcome: str) -> float:
    return _sample(OPERATIONS, operation=operation, accessor=accessor, kind=kind, auth_type=auth_type, outcome=outcome)


class TestIntegrationsSdkMetrics(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        register_source_kinds({"ably": AuthType.TOKEN})
        self.github = IntegrationManager.github.oauth.create(self.team.id, external_id="gh-1", config={})
        self.team_id = self.team.id
        self.github_id = self.github.id

    @parameterized.expand(
        [
            (
                "get_ok",
                "get",
                "named",
                "github",
                "oauth",
                "ok",
                lambda s: IntegrationManager.github.oauth.get(s.team_id, s.github_id),
            ),
            (
                "get_not_found",
                "get",
                "named",
                "github",
                "oauth",
                "not_found",
                lambda s: IntegrationManager.github.oauth.get(s.team_id, 0),
            ),
            (
                "get_any_kind",
                "get",
                "any",
                "multi",
                "any",
                "ok",
                lambda s: IntegrationManager.any.get(s.team_id, s.github_id),
            ),
            (
                "list_kind_any_auth",
                "list",
                "named",
                "github",
                "any",
                "ok",
                lambda s: IntegrationManager.github.any.list(s.team_id),
            ),
            (
                "find_kinds",
                "find",
                "kinds",
                "multi",
                "any",
                "ok",
                lambda s: IntegrationManager.kinds("github", "slack").find(s.team_id),
            ),
            (
                "count_by_external_id",
                "count_by_external_id",
                "named",
                "github",
                "oauth",
                "ok",
                lambda s: IntegrationManager.github.oauth.count_by_external_id("gh-1"),
            ),
            (
                "any_cross_team_error",
                "list_by_external_id",
                "any",
                "multi",
                "any",
                "error",
                lambda s: IntegrationManager.any.list_by_external_id("gh-1"),
            ),
            (
                "create_conflict",
                "create",
                "named",
                "github",
                "oauth",
                "conflict",
                lambda s: IntegrationManager.github.oauth.create(s.team_id, external_id="gh-1", config={}),
            ),
            (
                "upsert_ok",
                "upsert",
                "named",
                "github",
                "oauth",
                "ok",
                lambda s: IntegrationManager.github.oauth.upsert(s.team_id, "gh-2", config={}),
            ),
            (
                "update_ok",
                "update",
                "named",
                "github",
                "oauth",
                "ok",
                lambda s: IntegrationManager.github.oauth.update(s.team_id, s.github_id, config_patch={"a": 1}),
            ),
            (
                "update_not_found",
                "update",
                "named",
                "github",
                "oauth",
                "not_found",
                lambda s: IntegrationManager.github.oauth.update(s.team_id, 0, config_patch={"a": 1}),
            ),
            (
                "delete_ok",
                "delete",
                "named",
                "github",
                "oauth",
                "ok",
                lambda s: IntegrationManager.github.oauth.delete(s.team_id, s.github_id),
            ),
            (
                "source_get_not_found",
                "get",
                "source",
                "ably",
                "any",
                "not_found",
                lambda s: IntegrationManager.source("ably").any.get(s.team_id, s.github_id),
            ),
        ]
    )
    def test_operation_is_counted_with_its_outcome(
        self,
        _name: str,
        operation: str,
        accessor: str,
        kind: str,
        auth_type: str,
        outcome: str,
        call: Callable[["TestIntegrationsSdkMetrics"], Any],
    ) -> None:
        before = _counts(operation, accessor, kind, auth_type, outcome)
        before_duration = _sample(DURATION_COUNT, operation=operation, accessor=accessor, outcome=outcome)

        try:
            call(self)
        except Exception:
            assert outcome != "ok"

        assert _counts(operation, accessor, kind, auth_type, outcome) == before + 1
        assert _sample(DURATION_COUNT, operation=operation, accessor=accessor, outcome=outcome) == before_duration + 1

    def test_delete_in_use_is_counted(self) -> None:
        before = _counts("delete", "named", "github", "oauth", "in_use")

        with (
            patch.object(usages, "_registered", []),
            patch.object(
                usages,
                "_product_providers",
                [lambda team_id, integration_id: [IntegrationUsage(type="workflow", id="1", name="Flow")]],
            ),
        ):
            with self.assertRaises(IntegrationInUse):
                IntegrationManager.github.oauth.delete(self.team_id, self.github_id)

        assert _counts("delete", "named", "github", "oauth", "in_use") == before + 1

    def test_usages_counts_one_operation(self) -> None:
        before_get = _counts("get", "named", "github", "oauth", "ok")
        before_usages = _counts("usages", "named", "github", "oauth", "ok")

        IntegrationManager.github.oauth.usages(self.team_id, self.github_id)

        assert _counts("get", "named", "github", "oauth", "ok") == before_get
        assert _counts("usages", "named", "github", "oauth", "ok") == before_usages + 1

    def test_rows_returned_and_written_are_recorded(self) -> None:
        IntegrationManager.github.oauth.create(self.team_id, external_id="gh-2", config={})
        other_team = Team.objects.create(organization=self.organization, name="Other")
        IntegrationManager.github.oauth.create(other_team.id, external_id="gh-1", config={})
        returned_before = _sample(ROWS_RETURNED_SUM, operation="list", accessor="named")
        written_before = _sample(ROWS_WRITTEN, operation="update_by_external_id", kind="github")

        listed = IntegrationManager.github.oauth.list(self.team_id)
        changed = IntegrationManager.github.oauth.update_by_external_id("gh-1", IntegrationPatch(config_patch={"a": 1}))

        assert len(listed) == 2
        assert changed == 2
        assert _sample(ROWS_RETURNED_SUM, operation="list", accessor="named") == returned_before + 2
        assert _sample(ROWS_WRITTEN, operation="update_by_external_id", kind="github") == written_before + 2

    def test_async_form_counts_the_same_operation(self) -> None:
        before = _counts("get", "named", "github", "oauth", "not_found")

        with patch.object(IntegrationReader, "_row", side_effect=IntegrationNotFound("missing")):
            with self.assertRaises(IntegrationNotFound):
                async_to_sync(IntegrationManager.github.oauth.aget)(self.team_id, self.github_id)

        assert _counts("get", "named", "github", "oauth", "not_found") == before + 1

    @parameterized.expand(
        [
            ("label_error", lambda: patch.object(observability, "accessor_labels", side_effect=RuntimeError("x"))),
            ("sample_error", lambda: patch.object(observability._OPERATIONS, "labels", side_effect=RuntimeError("x"))),
        ]
    )
    def test_broken_metrics_do_not_break_the_call(self, _name: str, broken_metrics: Callable[[], Any]) -> None:
        with broken_metrics():
            assert IntegrationManager.github.oauth.get(self.team_id, self.github_id).id == self.github_id
            with self.assertRaises(IntegrationNotFound):
                IntegrationManager.github.oauth.get(self.team_id, 0)

    @parameterized.expand(
        [
            ("fresh", 10, None, False, "", "fresh"),
            ("expired", 800, None, False, "", "refreshed"),
            ("stale_token", 10, "old", True, "", "stale_token"),
            ("failed_refresh_sets_errors", 800, None, True, "TOKEN_REFRESH_FAILED", "error"),
            ("raising_refresh", 800, None, True, "raise", "error"),
        ]
    )
    def test_token_refresh_result(
        self, _name: str, refreshed_ago: int, stale: str | None, calls_refresh: bool, errors: str, result: str
    ) -> None:
        row = Integration.objects._with_auth(ANY).create(
            team=self.team,
            kind="resend",
            integration_id="resend-1",
            config={"expires_in": 900, "refreshed_at": int(time.time()) - refreshed_ago},
            sensitive_config={"access_token": "old", "refresh_token": "r1"},
        )
        before = _sample(TOKEN_REFRESH, kind="resend", result=result)

        def refresh(oauth: OauthIntegration) -> None:
            if errors == "raise":
                raise RuntimeError("provider down")
            oauth.integration.errors = errors

        with patch.object(OauthIntegration, "refresh_access_token", autospec=True, side_effect=refresh) as mocked:
            try:
                OAuthAccessor(kind="resend").refresh_access_token(self.team_id, row.id, stale_access_token=stale)
            except RuntimeError:
                assert errors == "raise"

        assert mocked.call_count == (1 if calls_refresh or refreshed_ago > 600 else 0)
        assert _sample(TOKEN_REFRESH, kind="resend", result=result) == before + 1
