import time
import base64
import hashlib
from datetime import timedelta
from decimal import Decimal

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import connection
from django.test import (
    Client as DjangoClient,
    override_settings,
)
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

import requests
from parameterized import parameterized
from urllib3 import HTTPConnectionPool
from urllib3.exceptions import MaxRetryError, NewConnectionError, ProtocolError

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization
from posthog.models.user import User

from products.ai_gateway.backend.models import DevGatewayToken

_POST = "products.ai_gateway.backend.logic.requests.post"
_VIEW_IMPERSONATED = "products.ai_gateway.backend.presentation.views.is_impersonated"
URL = "/api/ai_gateway/dev_tokens/"
VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


def _response(status_code: int, body: dict | None = None) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = body or {}
    return response


def _minted(token: str = "phe_new") -> MagicMock:
    return _response(201, {"token": token, "expires_at": "2099-01-01T00:00:00Z", "cap_usd": "25"})


class _DevGatewaySettings(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        override = override_settings(
            DEV_GATEWAY_URL="https://ai-gateway.test/v1",
            DEV_GATEWAY_MINT_KEY="phs_dev",
            DEV_GATEWAY_TEAM_ID=self.team.id,
            DEV_GATEWAY_TOKEN_CAP_USD="25",
            DEV_GATEWAY_DAILY_CAP_USD="50",
        )
        override.enable()
        self.addCleanup(override.disable)
        self.user.is_staff = True
        self.user.save()


class TestDevTokens(_DevGatewaySettings):
    def _rows(self, **filters):
        return DevGatewayToken.objects.unscoped().filter(**filters)

    def test_mint_pins_the_session_user_and_stores_only_the_hash(self):
        with patch(_POST, return_value=_minted("phe_secret")) as post:
            response = self.client.post(URL)

        assert response.status_code == 201, response.json()
        assert response.json()["token"] == "phe_secret"
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        assert url == "https://ai-gateway.test/v1/tokens"
        assert kwargs["headers"] == {"Authorization": "Bearer phs_dev"}
        assert kwargs["json"] == {
            "cap_usd": "25",
            "ttl_seconds": 28800,
            "product": "dev",
            "user": self.user.distinct_id,
        }
        row = self._rows(user=self.user).get()
        assert row.token_hash == hashlib.sha256(b"phe_secret").hexdigest()
        assert row.client == "web"
        entry = ActivityLog.objects.get(scope="DevGatewayToken", item_id=str(row.id))
        assert (entry.activity, entry.user_id, entry.team_id) == ("minted", self.user.id, self.team.id)
        assert "phe_secret" not in str(entry.detail)

    @parameterized.expand(
        [
            ("not_staff", {"is_staff": False}, "not_staff"),
            ("outside_email", {"email": "someone@example.com"}, "not_staff"),
            ("lookalike_domain", {"email": "someone@evilposthog.com"}, "not_staff"),
            ("no_distinct_id", {"distinct_id": ""}, "not_staff"),
            ("unverified_email", {"is_email_verified": False}, "not_staff"),
        ]
    )
    def test_ineligible_user_never_reaches_the_gateway(self, _name, fields, code):
        for field, value in fields.items():
            setattr(self.user, field, value)
        self.user.save()
        with patch(_POST) as post:
            response = self.client.post(URL)
        assert response.status_code == 403
        assert response.json()["code"] == code
        post.assert_not_called()

    def test_unconfigured_instance_never_reaches_the_gateway(self):
        with override_settings(DEV_GATEWAY_MINT_KEY=""), patch(_POST) as post:
            response = self.client.post(URL)
        assert response.status_code == 503
        assert response.json()["code"] == "unconfigured"
        post.assert_not_called()

    @parameterized.expand(
        [
            ("usage", "get", "usage/", {}),
            ("team_usage", "get", "team_usage/", {}),
            ("create", "post", "", {}),
            ("revoke", "post", "revoke/", {}),
            ("cli_authorize", "post", "cli_authorize/", {"code_challenge": CHALLENGE}),
        ]
    )
    def test_every_session_view_refuses_impersonation(self, _name, method, path, body):
        # The middleware check reads the session only, so this pins each view's own guard.
        with patch(_VIEW_IMPERSONATED, return_value=True), patch(_POST) as post:
            response = getattr(self.client, method)(f"{URL}{path}", body)
        assert response.status_code == 403
        assert response.json()["code"] == "impersonated"
        post.assert_not_called()
        assert not self._rows(user=self.user).exists()

    @parameterized.expand(
        [
            # GET passes the middleware, so the view guard is the only refusal.
            ("usage", "get", "usage/", {}, "impersonated"),
            ("team_usage", "get", "team_usage/", {}, "impersonated"),
            ("create", "post", "", {}, "impersonation_path_blocked"),
            ("revoke", "post", "revoke/", {}, "impersonation_path_blocked"),
            (
                "cli_authorize",
                "post",
                "cli_authorize/",
                {"code_challenge": CHALLENGE},
                "impersonation_path_blocked",
            ),
        ]
    )
    @override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_SECRET=None)
    def test_loginas_session_is_refused(self, _name, method, path, body, code):
        # loginas refuses staff targets, so the impersonated user is a customer.
        target = User.objects.create_and_join(self.organization, "target@example.com", "123456")
        client = DjangoClient()
        client.force_login(self.user)
        client.post(
            reverse("loginas-user-login", kwargs={"user_id": target.id}),
            data={"read_only": "false", "reason": "Test impersonation"},
        )
        with patch(_POST) as post:
            if method == "get":
                response = client.get(f"{URL}{path}")
            else:
                response = client.post(f"{URL}{path}", body, content_type="application/json")
        assert response.status_code == 403
        assert response.json()["code"] == code
        post.assert_not_called()
        assert not self._rows(user=target).exists()

    def test_daily_cap_is_reserved_before_the_gateway_call(self):
        with patch(_POST, side_effect=[_minted(f"phe_{i}") for i in range(2)]):
            for _ in range(2):
                assert self.client.post(URL).status_code == 201

        with patch(_POST) as post:
            response = self.client.post(URL)
        assert response.status_code == 429
        assert response.json()["code"] == "daily_limit"
        assert "$50.00 limit" in response.json()["detail"]
        post.assert_not_called()

        status = _response(
            200, {"tokens": [{"token_hash": hashlib.sha256(b"phe_1").hexdigest(), "remaining_usd": "21.5"}]}
        )
        with patch(_POST, return_value=status) as post:
            usage = self.client.get(f"{URL}usage/").json()
        assert post.call_args.args[0] == "https://ai-gateway.test/v1/tokens/status"
        assert Decimal(usage["used_usd"]) == Decimal("50")
        assert [t["status"] for t in usage["tokens"]] == ["live", "live"]
        # Newest first; the gateway omitted phe_0, so its remaining is unknown.
        assert [t["remaining_usd"] for t in usage["tokens"]] == ["21.500000", None]

    def test_reserve_locks_the_user_row_before_summing_the_window(self):
        with patch(_POST, return_value=_minted()), CaptureQueriesContext(connection) as queries:
            assert self.client.post(URL).status_code == 201
        sqls = [q["sql"] for q in queries.captured_queries]
        lock = next(
            i for i, sql in enumerate(sqls) if 'FROM "posthog_user"' in sql and sql.rstrip().endswith("FOR UPDATE")
        )
        window_sum = next(i for i, sql in enumerate(sqls) if "SUM(" in sql and "ai_gateway_devgatewaytoken" in sql)
        reserve = next(i for i, sql in enumerate(sqls) if sql.startswith('INSERT INTO "ai_gateway_devgatewaytoken"'))
        assert lock < window_sum < reserve

    @parameterized.expand(
        [
            ("refused", {"return_value": _response(500)}, False),
            ("body_without_expiry", {"return_value": _response(201, {"token": "phe_x"})}, True),
            (
                "non_json_body",
                {"return_value": MagicMock(status_code=201, json=MagicMock(side_effect=ValueError))},
                True,
            ),
            ("read_timeout", {"side_effect": requests.ReadTimeout()}, True),
            ("connection_reset", {"side_effect": requests.ConnectionError(ProtocolError("reset"))}, True),
            ("connect_timeout", {"side_effect": requests.ConnectTimeout()}, False),
            (
                "connection_refused",
                {
                    "side_effect": requests.ConnectionError(
                        MaxRetryError(HTTPConnectionPool("gateway"), "/v1/tokens", NewConnectionError(None, "refused"))
                    )
                },
                False,
            ),
            ("invalid_url", {"side_effect": requests.exceptions.InvalidURL()}, False),
        ]
    )
    def test_failed_mint_keeps_the_reservation_only_when_ambiguous(self, _name, post_kwargs, kept):
        with patch(_POST, **post_kwargs):
            response = self.client.post(URL)
        assert response.status_code == 503
        assert response.json()["code"] == "mint_failed"
        assert self._rows(user=self.user, token_hash__isnull=True).exists() == kept

    @parameterized.expand(
        [
            ("create", "", {}),
            ("cli_authorize", "cli_authorize/", {"code_challenge": CHALLENGE}),
        ]
    )
    def test_stale_session_must_reauthenticate_to_mint(self, _name, path, body):
        session = self.client.session
        stale = time.time() - settings.SESSION_SENSITIVE_ACTIONS_AGE - 60
        session[settings.SESSION_COOKIE_CREATED_AT_KEY] = stale
        session[settings.SESSION_LAST_REAUTH_AT_KEY] = stale
        session.save()
        with patch(_POST) as post:
            response = self.client.post(f"{URL}{path}", body)
        assert response.status_code == 403
        assert response.json()["code"] == "sensitive_action_required_reauth"
        post.assert_not_called()
        assert self.client.post(f"{URL}revoke/", {}).status_code == 200

    @parameterized.expand(
        [
            ("endpoint_not_deployed", {"return_value": _response(404)}),
            ("unreachable", {"side_effect": requests.ConnectionError("refused")}),
            ("unreadable", {"return_value": _response(200, {"tokens": [{"token_hash": "a"}]})}),
        ]
    )
    def test_usage_renders_without_remaining_when_status_fails(self, _name, post_kwargs):
        with patch(_POST, return_value=_minted()):
            self.client.post(URL)
        with patch(_POST, **post_kwargs):
            response = self.client.get(f"{URL}usage/")
        assert response.status_code == 200
        assert response.json()["tokens"][0]["remaining_usd"] is None

    def test_token_status_is_authenticated_by_the_bearer_alone(self):
        with patch(_POST, return_value=_minted("phe_held")):
            self.client.post(URL)
        self.client.logout()

        status = _response(
            200, {"tokens": [{"token_hash": hashlib.sha256(b"phe_held").hexdigest(), "remaining_usd": "3"}]}
        )
        with patch(_POST, return_value=status):
            held = self.client.post(f"{URL}token_status/", {"token": "phe_held"})
        assert held.status_code == 200, held.json()
        assert (held.json()["status"], held.json()["remaining_usd"]) == ("live", "3.000000")

        with patch(_POST) as post:
            unknown = self.client.post(f"{URL}token_status/", {"token": "phe_guessed"})
        assert unknown.status_code == 404
        post.assert_not_called()

    def test_team_usage_refuses_staff_outside_the_paying_organization(self):
        outsider = User.objects.create_and_join(
            Organization.objects.create(name="Elsewhere"), "outsider@posthog.com", None, is_staff=True
        )
        self.client.force_login(outsider)
        response = self.client.get(f"{URL}team_usage/")
        assert response.status_code == 403
        assert response.json()["code"] == "not_member"

    def test_revoke_sends_only_the_callers_hashes(self):
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None, is_staff=True)
        others = DevGatewayToken.objects.unscoped().create(
            team=self.team,
            user=other,
            client="web",
            cap_usd=Decimal("25"),
            token_hash="b" * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        with patch(_POST, return_value=_minted("phe_mine")):
            self.client.post(URL)

        with patch(_POST) as post:
            foreign = self.client.post(f"{URL}revoke/", {"id": str(others.id)})
        assert foreign.status_code == 404
        post.assert_not_called()

        with patch(_POST, return_value=_response(200, {"revoked": True, "revoked_count": 1})) as post:
            response = self.client.post(f"{URL}revoke/", {})

        assert response.status_code == 200
        assert response.json() == {"revoked_count": 1}
        assert post.call_args.args[0] == "https://ai-gateway.test/v1/tokens/revoke"
        assert post.call_args.kwargs["json"] == {"token_hashes": [hashlib.sha256(b"phe_mine").hexdigest()]}
        assert self._rows(user=self.user, revoked_at__isnull=False).count() == 1
        assert self._rows(user=other, revoked_at__isnull=True).count() == 1
        mine = self._rows(user=self.user).get()
        assert (
            ActivityLog.objects.filter(scope="DevGatewayToken", item_id=str(mine.id), activity="revoked").count() == 1
        )
        assert self.client.get(f"{URL}usage/").json()["tokens"][0]["status"] == "revoked"

    def test_cli_code_exchanges_once_for_the_authorizing_user(self):
        code = self.client.post(f"{URL}cli_authorize/", {"code_challenge": CHALLENGE}).json()["code"]
        self.client.logout()

        with patch(_POST) as post:
            wrong = self.client.post(f"{URL}cli_exchange/", {"code": code, "code_verifier": "w" * 43})
        assert wrong.status_code == 400
        post.assert_not_called()

        code = self._authorize()
        with patch(_POST, return_value=_minted("phe_cli")) as post:
            response = self.client.post(f"{URL}cli_exchange/", {"code": code, "code_verifier": VERIFIER})
        assert response.status_code == 201, response.json()
        assert post.call_args.kwargs["json"]["user"] == self.user.distinct_id
        assert self._rows(user=self.user, client="cli").count() == 1

        with patch(_POST) as post:
            replay = self.client.post(f"{URL}cli_exchange/", {"code": code, "code_verifier": VERIFIER})
        assert replay.status_code == 400
        post.assert_not_called()

    def test_cli_exchange_refuses_a_deactivated_user(self):
        code = self._authorize()
        self.user.is_active = False
        self.user.save()
        with patch(_POST) as post:
            response = self.client.post(f"{URL}cli_exchange/", {"code": code, "code_verifier": VERIFIER})
        assert response.status_code == 403
        assert response.json()["code"] == "not_staff"
        post.assert_not_called()

    def test_cli_exchange_rechecks_eligibility(self):
        code = self._authorize()
        self.user.is_staff = False
        self.user.save()
        with patch(_POST) as post:
            response = self.client.post(f"{URL}cli_exchange/", {"code": code, "code_verifier": VERIFIER})
        assert response.status_code == 403
        post.assert_not_called()

    def test_cli_authorize_needs_a_session(self):
        self.client.logout()
        response = self.client.post(f"{URL}cli_authorize/", {"code_challenge": CHALLENGE})
        assert response.status_code in (401, 403)

    def _authorize(self) -> str:
        self.client.force_login(self.user)
        code = self.client.post(f"{URL}cli_authorize/", {"code_challenge": CHALLENGE}).json()["code"]
        self.client.logout()
        return code


class TestDevTeamUsage(ClickhouseTestMixin, _DevGatewaySettings):
    def _generation(self, distinct_id: str | None, cost: str, days_ago: float, source: str = "pinned") -> None:
        assert distinct_id is not None
        _create_event(
            team=self.team,
            event="$ai_generation",
            distinct_id=distinct_id,
            timestamp=timezone.now() - timedelta(days=days_ago),
            properties={
                "$ai_product": "dev",
                "$ai_product_source": source,
                "$ai_user": distinct_id,
                "$ai_total_cost_usd": cost,
            },
        )

    def test_team_usage_sums_pinned_spend_per_user_by_window(self):
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None, is_staff=True)
        DevGatewayToken.objects.unscoped().create(
            team=self.team,
            user=self.user,
            client="web",
            cap_usd=Decimal("25"),
            token_hash="a" * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self._generation(self.user.distinct_id, "1.5", days_ago=0.1)
        self._generation(self.user.distinct_id, "2", days_ago=3)
        self._generation(self.user.distinct_id, "4", days_ago=10)
        # A phs_ caller can claim the product by header; only pinned spend counts.
        self._generation(self.user.distinct_id, "100", days_ago=0.1, source="header")
        self._generation(other.distinct_id, "0.25", days_ago=0.1)
        self._generation("orphan-distinct-id", "0.5", days_ago=0.1)
        flush_persons_and_events()

        response = self.client.get(f"{URL}team_usage/")

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["paying_team_id"] == self.team.id
        rows = {row["distinct_id"]: row for row in body["users"]}
        mine = rows[self.user.distinct_id]
        assert [Decimal(mine[k]) for k in ("spend_usd_24h", "spend_usd_7d", "spend_usd_30d")] == [
            Decimal("1.5"),
            Decimal("3.5"),
            Decimal("7.5"),
        ]
        assert (mine["tokens_minted_24h"], mine["live_tokens"], Decimal(mine["reserved_usd_24h"])) == (
            1,
            1,
            Decimal("25"),
        )
        assert rows[other.distinct_id]["email"] == "other@posthog.com"
        assert rows[other.distinct_id]["tokens_minted_30d"] == 0
        assert rows["orphan-distinct-id"]["user_id"] is None
        assert body["users"][0]["distinct_id"] == self.user.distinct_id

    def test_team_usage_lists_mint_and_revoke_activity_newest_first(self):
        with patch(_POST, return_value=_minted("phe_audit")):
            self.client.post(URL)
        with patch(_POST, return_value=_response(200, {"revoked": True, "revoked_count": 1})):
            self.client.post(f"{URL}revoke/", {})

        activity = self.client.get(f"{URL}team_usage/").json()["activity"]

        assert [(a["activity"], a["actor_email"], a["owner_email"], a["client"], a["cap_usd"]) for a in activity] == [
            ("revoked", self.user.email, self.user.email, "web", "25.00"),
            ("minted", self.user.email, self.user.email, "web", "25.00"),
        ]
