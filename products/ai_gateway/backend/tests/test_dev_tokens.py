import base64
import hashlib
from datetime import timedelta
from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.user import User

from products.ai_gateway.backend.models import DevGatewayToken

_POST = "products.ai_gateway.backend.logic.requests.post"
_FLAG = "products.ai_gateway.backend.logic.posthoganalytics.feature_enabled"
URL = "/api/ai_gateway/dev_tokens/"
VERIFIER = "v" * 43
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


def _response(status_code: int, body: dict | None = None) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = body or {}
    return response


def _minted(token: str = "phe_new") -> MagicMock:
    return _response(201, {"token": token, "expires_at": "2099-01-01T00:00:00Z", "cap_usd": "25"})


class TestDevTokens(APIBaseTest):
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
        flag = patch(_FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)
        self.user.is_staff = True
        self.user.save()

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

    def test_impersonated_session_cannot_mint(self):
        with patch("products.ai_gateway.backend.presentation.views.is_impersonated", return_value=True):
            with patch(_POST) as post:
                response = self.client.post(URL)
        assert response.status_code == 403
        assert response.json()["code"] == "impersonated"
        post.assert_not_called()

    def test_kill_switch_refuses_only_on_explicit_false(self):
        with patch(_FLAG, return_value=False), patch(_POST) as post:
            response = self.client.post(URL)
        assert response.json()["code"] == "disabled"
        post.assert_not_called()

        with patch(_FLAG, side_effect=Exception("flags down")), patch(_POST, return_value=_minted()):
            assert self.client.post(URL).status_code == 201

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

        usage = self.client.get(f"{URL}usage/").json()
        assert Decimal(usage["used_usd"]) == Decimal("50")
        assert [t["status"] for t in usage["tokens"]] == ["live", "live"]

    def test_failed_mint_does_not_spend_the_daily_cap(self):
        with patch(_POST, return_value=_response(500)):
            response = self.client.post(URL)
        assert response.status_code == 503
        assert response.json()["code"] == "mint_failed"
        assert not self._rows(user=self.user).exists()

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

        replay = self.client.post(f"{URL}cli_exchange/", {"code": code, "code_verifier": VERIFIER})
        assert replay.status_code == 400

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
