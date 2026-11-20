import time
from typing import TypedDict

from django.core.cache import caches
from django.db import transaction

import requests
import structlog
from celery import Task, shared_task
from redis.exceptions import RedisError
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed
from urllib3.exceptions import InvalidHeader
from urllib3.util import Retry

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
    retry_delay: float
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


def schedule_poll(user_id: int, login: DeviceLogin, delay: float | None = None) -> None:
    with transaction.atomic():
        CodexUserIntegration._lock_user(user_id)
        if get_login(user_id, login["login_id"])["status"] not in ("starting", "pending"):
            return
        interval = max(login["interval"], delay or 0)
        remaining = login["expires_at"] - time.time()
        if remaining <= interval:
            update_login(user_id, login["login_id"], "expired")
            return
        login["next_poll_at"] = time.time() + interval
        caches["codex_login"].set(login_key(user_id), login, timeout=remaining)
        transaction.on_commit(
            lambda: complete_codex_login.apply_async(
                (user_id, login["login_id"]), countdown=interval, expires=remaining
            )
        )


def claim_login(user_id: int, login_id: str) -> DeviceLogin | None:
    with transaction.atomic():
        CodexUserIntegration._lock_user(user_id)
        login: DeviceLogin | None = caches["codex_login"].get(login_key(user_id))
        if not login or login["login_id"] != login_id or login["status"] not in ("starting", "pending"):
            return None
        remaining = login["expires_at"] - time.time()
        if remaining <= 0:
            update_login(user_id, login_id, "expired")
            return None
        if login.get("next_poll_at", 0) > time.time():
            return None
        login["next_poll_at"] = time.time() + 60
        caches["codex_login"].set(login_key(user_id), login, timeout=remaining)
        return login


def poll_approval(user_id: int, login: DeviceLogin) -> requests.Response | None:
    response = None
    try:
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
            login.pop("retry_delay", None)
            schedule_poll(user_id, login)
            return None
        if response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()
            return response
    except (requests.Timeout, requests.ConnectionError):
        pass
    retry_after = 0.0
    if response is not None:
        try:
            retry_after = Retry().parse_retry_after(response.headers.get("Retry-After", "0"))
        except (InvalidHeader, OverflowError):
            pass
    retry_login(user_id, login, retry_after)
    return None


def retry_login(user_id: int, login: DeviceLogin, retry_after: float = 0) -> None:
    login.setdefault("interval", 5)
    login["retry_delay"] = min(60, login.get("retry_delay", 5) * 2)
    schedule_poll(user_id, login, max(login["retry_delay"], retry_after))


def check_login_access(user: User, login: DeviceLogin) -> bool:
    from posthog.api.user_integration_codex import DesktopAccessUnavailable, ensure_codex_connect_enabled

    try:
        ensure_codex_connect_enabled(user)
        return True
    except DesktopAccessUnavailable:
        retry_login(user.id, login)
        return False


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, soft_time_limit=55, time_limit=60)
@skip_team_scope_audit
def complete_codex_login(self: Task, user_id: int, login_id: str) -> None:
    from posthog.api.user_integration_codex import DesktopAccessUnavailable, ensure_codex_connect_enabled

    exchange_started = False
    try:
        login = claim_login(user_id, login_id)
        if login is None:
            return
        user = User.objects.get(id=user_id, is_active=True)
        if not check_login_access(user, login):
            return
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
        approval = poll_approval(user_id, login)
        if approval is None:
            return
        user = User.objects.get(id=user_id, is_active=True)
        if not check_login_access(user, login):
            return
        grant = approval.json()
        exchange_started = True
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
        with transaction.atomic():
            CodexUserIntegration._lock_user(user_id)
            if get_login(user_id, login_id)["status"] != "pending":
                return
            CodexUserIntegration.connect(user_id, tokens, source="device_login", device_login_id=login_id)
            Retrying(
                retry=retry_if_exception_type(DesktopAccessUnavailable),
                stop=stop_after_attempt(2),
                wait=wait_fixed(5),
                reraise=True,
            )(lambda: ensure_codex_connect_enabled(User.objects.get(id=user_id, is_active=True)))
            if time.time() >= login["expires_at"]:
                raise TimeoutError("Device login expired")
            transaction.on_commit(
                lambda: Retrying(
                    retry=retry_if_exception_type(RedisError),
                    stop=stop_after_attempt(3),
                    wait=wait_fixed(2),
                    reraise=True,
                )(update_login, user_id, login_id, "connected"),
                robust=True,
            )
            transaction.on_commit(lambda: capture_login_result(user, "connected"))
    except Exception as error:
        if isinstance(error, RedisError) and not exchange_started:
            raise self.retry(countdown=60, max_retries=3) from None
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
