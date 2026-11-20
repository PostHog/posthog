import time
from typing import TypedDict

from django.core.cache import caches
from django.db import transaction

import structlog
from celery import shared_task

from posthog.egress.openai_auth import OPENAI_OAUTH_TOKEN_URL, openai_auth_request
from posthog.models.integration.codex import CODEX_OAUTH_CLIENT_ID, CodexUserIntegration, parse_codex_auth_json
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

LOGIN_TIMEOUT = 10 * 60
DEVICE_AUTH_URL = "https://auth.openai.com/api/accounts/deviceauth"


class CodexLogin(TypedDict):
    login_id: str
    status: str
    user_code: str | None


class DeviceLogin(CodexLogin, total=False):
    expires_at: float
    device_auth_id: str
    interval: int
    next_poll_at: float


def login_key(user_id: int) -> str:
    return f"codex_device_login:{user_id}"


def get_login(user_id: int, login_id: str) -> CodexLogin:
    login = caches["codex_login"].get(login_key(user_id))
    if login and login["login_id"] == login_id:
        return {"login_id": login_id, "status": login["status"], "user_code": login["user_code"]}
    return {"login_id": login_id, "status": "expired", "user_code": None}


def update_login(user_id: int, login_id: str, status: str, user_code: str | None = None) -> bool:
    with transaction.atomic():
        CodexUserIntegration._lock_user(user_id)
        if get_login(user_id, login_id)["status"] not in ("starting", "pending"):
            return False
        caches["codex_login"].set(
            login_key(user_id),
            {"login_id": login_id, "status": status, "user_code": user_code},
            timeout=LOGIN_TIMEOUT,
        )
        return True


def start_login(user_id: int, login_id: str) -> CodexLogin:
    login: DeviceLogin = {
        "login_id": login_id,
        "status": "starting",
        "user_code": None,
        "expires_at": time.time() + LOGIN_TIMEOUT,
    }
    with transaction.atomic():
        CodexUserIntegration._lock_user(user_id)
        caches["codex_login"].set(login_key(user_id), login, timeout=LOGIN_TIMEOUT)
        transaction.on_commit(lambda: complete_codex_login.delay(user_id, login_id))
    return get_login(user_id, login_id)


def cancel_login(user_id: int, login_id: str) -> None:
    with transaction.atomic():
        CodexUserIntegration._lock_user(user_id)
        integration = CodexUserIntegration.for_user(user_id)
        if integration and integration.integration.config.get("device_login_id") == login_id:
            integration.disconnect(source="device_login")
        if get_login(user_id, login_id)["status"] != "expired":
            caches["codex_login"].set(
                login_key(user_id),
                {"login_id": login_id, "status": "canceled", "user_code": None},
                timeout=LOGIN_TIMEOUT,
            )


def schedule_poll(user_id: int, login: DeviceLogin) -> None:
    interval = login["interval"]
    remaining = login["expires_at"] - time.time()
    if remaining <= interval:
        update_login(user_id, login["login_id"], "expired")
        return
    login["next_poll_at"] = time.time() + interval
    caches["codex_login"].set(login_key(user_id), login, timeout=remaining)
    transaction.on_commit(
        lambda: complete_codex_login.apply_async((user_id, login["login_id"]), countdown=interval, expires=remaining)
    )


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, soft_time_limit=55, time_limit=60)
@skip_team_scope_audit
def complete_codex_login(user_id: int, login_id: str) -> None:
    from posthog.api.user_integration_codex import ensure_codex_connect_enabled

    try:
        with transaction.atomic():
            CodexUserIntegration._lock_user(user_id)
            login: DeviceLogin | None = caches["codex_login"].get(login_key(user_id))
            if not login or login["login_id"] != login_id or login["status"] not in ("starting", "pending"):
                return
            if login["expires_at"] <= time.time():
                update_login(user_id, login_id, "expired")
                return
            if login.get("next_poll_at", 0) > time.time():
                return
            user = User.objects.get(id=user_id, is_active=True)
            ensure_codex_connect_enabled(user)
            if login["status"] == "starting":
                response = openai_auth_request(
                    "POST",
                    f"{DEVICE_AUTH_URL}/usercode",
                    source="device_login",
                    endpoint="device_usercode",
                    timeout=10,
                    allow_redirects=False,
                    json={"client_id": CODEX_OAUTH_CLIENT_ID},
                )
                response.raise_for_status()
                body = response.json()
                if not all(isinstance(body.get(key), str) and body[key] for key in ("device_auth_id", "user_code")):
                    raise ValueError("Invalid device login response")
                login.update(
                    {
                        "status": "pending",
                        "user_code": body["user_code"],
                        "device_auth_id": body["device_auth_id"],
                        "interval": max(5, int(body.get("interval", 5))),
                    }
                )
                schedule_poll(user_id, login)
                return
            login["next_poll_at"] = time.time() + 60
            caches["codex_login"].set(login_key(user_id), login, timeout=login["expires_at"] - time.time())
            response = openai_auth_request(
                "POST",
                f"{DEVICE_AUTH_URL}/token",
                source="device_login",
                endpoint="device_token",
                timeout=10,
                allow_redirects=False,
                json={"device_auth_id": login["device_auth_id"], "user_code": login["user_code"]},
            )
            if response.status_code in (403, 404):
                schedule_poll(user_id, login)
                return
            response.raise_for_status()
            grant = response.json()
            response = openai_auth_request(
                "POST",
                OPENAI_OAUTH_TOKEN_URL,
                source="device_login",
                endpoint="token",
                timeout=10,
                allow_redirects=False,
                data={
                    "grant_type": "authorization_code",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "redirect_uri": "https://auth.openai.com/deviceauth/callback",
                    "code": grant["authorization_code"],
                    "code_verifier": grant["code_verifier"],
                },
            )
            response.raise_for_status()
            tokens = parse_codex_auth_json({"tokens": response.json()})
            integration = CodexUserIntegration.connect(user_id, tokens, source="device_login").integration
            if time.time() >= login["expires_at"]:
                raise TimeoutError("Device login expired")
            integration.config["device_login_id"] = login_id
            integration.save(update_fields=["config"])
            transaction.on_commit(lambda: update_login(user_id, login_id, "connected"))
            transaction.on_commit(lambda: capture_login_result(user, "connected"))
    except Exception as error:
        logger.warning("codex_device_login_failed", reason=type(error).__name__)
        if update_login(user_id, login_id, "expired" if isinstance(error, TimeoutError) else "failed"):
            user = User.objects.filter(id=user_id).first()
            if user is not None:
                capture_login_result(user, "failed")


def capture_login_result(user: User, state: str) -> None:
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=user.distinct_id,
            event="codex subscription connected" if state == "connected" else "codex subscription connect failed",
            properties={"method": "device_code", "outcome": state},
        )
