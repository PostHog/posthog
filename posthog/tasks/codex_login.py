import os
import json
import time
import tempfile
import selectors
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypedDict

from django.core.cache import cache, caches
from django.db import transaction

import structlog
from celery import shared_task

from posthog.models.integration.codex import CodexUserIntegration, parse_codex_auth_json
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

LOGIN_TIMEOUT = 10 * 60


class CodexLogin(TypedDict):
    login_id: str
    status: str
    user_code: str | None


def login_key(user_id: int) -> str:
    return f"codex_device_login:{user_id}"


def get_login(user_id: int, login_id: str) -> CodexLogin:
    login = caches["codex_login"].get(login_key(user_id))
    if login and login["login_id"] == login_id:
        return login
    return {"login_id": login_id, "status": "expired", "user_code": None}


def update_login(user_id: int, login_id: str, status: str, user_code: str | None = None) -> bool:
    with transaction.atomic():
        CodexUserIntegration._lock_user(user_id)
        if get_login(user_id, login_id)["status"] not in ("starting", "pending"):
            return False
        cache.set(
            login_key(user_id),
            {"login_id": login_id, "status": status, "user_code": user_code},
            timeout=LOGIN_TIMEOUT,
        )
        return True


def start_login(user_id: int, login_id: str) -> CodexLogin:
    login: CodexLogin = {"login_id": login_id, "status": "starting", "user_code": None}
    with transaction.atomic():
        CodexUserIntegration._lock_user(user_id)
        cache.set(login_key(user_id), login, timeout=LOGIN_TIMEOUT)
        transaction.on_commit(lambda: complete_codex_login.delay(user_id, login_id))
    return login


def cancel_login(user_id: int, login_id: str) -> None:
    update_login(user_id, login_id, "canceled")


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=LOGIN_TIMEOUT + 15,
    time_limit=LOGIN_TIMEOUT + 30,
)
@skip_team_scope_audit
def complete_codex_login(user_id: int, login_id: str) -> None:
    if not cache.add(f"codex_device_login_worker:{user_id}:{login_id}", True, timeout=LOGIN_TIMEOUT + 30):
        return
    try:
        if get_login(user_id, login_id)["status"] != "starting":
            return
        with tempfile.TemporaryDirectory(prefix="codex-login-") as home:
            with subprocess.Popen(
                ["codex", "app-server", "-c", 'cli_auth_credentials_store="file"'],
                cwd=home,
                env={
                    **{
                        key: value
                        for key, value in os.environ.items()
                        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
                    },
                    "PATH": os.defpath + ":/usr/local/bin",
                    "CODEX_HOME": home,
                },
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ) as process:
                try:
                    run_login(process, user_id, login_id)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            with transaction.atomic():
                CodexUserIntegration._lock_user(user_id)
                if get_login(user_id, login_id)["status"] != "pending":
                    return
                if not User.objects.filter(id=user_id, is_active=True).exists():
                    raise RuntimeError("Account is inactive")
                tokens = parse_codex_auth_json(json.loads(Path(home, "auth.json").read_text()))
                CodexUserIntegration.connect(user_id, tokens, source="device_login")
                transaction.on_commit(lambda: update_login(user_id, login_id, "connected"))
    except TimeoutError:
        update_login(user_id, login_id, "expired")
    except Exception as error:
        logger.warning("codex_device_login_failed", reason=type(error).__name__)
        update_login(user_id, login_id, "failed")
    finally:
        state = get_login(user_id, login_id)["status"]
        user = User.objects.filter(id=user_id).first()
        if user is not None and state in ("connected", "failed", "expired"):
            with ph_scoped_capture() as capture:
                capture(
                    distinct_id=user.distinct_id,
                    event="codex subscription connected"
                    if state == "connected"
                    else "codex subscription connect failed",
                    properties={"method": "device_code", "outcome": state},
                )


def run_login(process: subprocess.Popen[bytes], user_id: int, login_id: str) -> None:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(
        json.dumps(
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "posthog", "version": "1"}}}
        ).encode()
        + b"\n"
    )
    process.stdin.flush()
    provider_login_id: str | None = None
    for message in login_messages(process, user_id, login_id):
        if "error" in message:
            raise RuntimeError("Codex login failed")
        if message.get("id") == 1:
            process.stdin.write(
                b'{"method":"initialized"}\n{"id":2,"method":"account/login/start","params":{"type":"chatgptDeviceCode"}}\n'
            )
            process.stdin.flush()
        elif message.get("id") == 2:
            result = message["result"]
            provider_login_id = result["loginId"]
            if result["verificationUrl"] != "https://auth.openai.com/codex/device":
                raise RuntimeError("Unexpected device login URL")
            if not update_login(user_id, login_id, "pending", result["userCode"]):
                return
        elif message.get("method") == "account/login/completed":
            params = message["params"]
            if provider_login_id is not None and params.get("loginId") == provider_login_id:
                if not params.get("success"):
                    raise RuntimeError("Device login was not approved")
                return


def login_messages(process: subprocess.Popen[bytes], user_id: int, login_id: str) -> Iterator[dict[str, Any]]:
    assert process.stdout is not None
    deadline = time.monotonic() + LOGIN_TIMEOUT
    buffer = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            if get_login(user_id, login_id)["status"] not in ("starting", "pending"):
                return
            if not selector.select(timeout=1):
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Codex login stopped")
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                yield json.loads(line)
    raise TimeoutError("Device login expired")
