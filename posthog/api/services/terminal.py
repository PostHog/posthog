import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from django.conf import settings

from redis.exceptions import LockError, RedisError
from redis.lock import Lock
from rest_framework.exceptions import APIException, NotFound, Throttled

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

from products.tasks.backend.facade.sandbox import (
    SandboxConfig,
    SandboxNotFoundError,
    SandboxTemplate,
    get_sandbox_class_for_backend,
)

SANDBOX_LIFETIME_SECONDS = 3600
SANDBOX_SIZES = {"small": (1, 2), "balanced": (4, 8), "large": (8, 16), "high_memory": (8, 32)}


class TerminalSandboxUnavailable(APIException):
    status_code = 503
    default_detail = "Could not start the Modal sandbox. Try again in a moment."


class TerminalSandboxService:
    def __init__(self, team_id: int, user_id: int) -> None:
        self.team_id = team_id
        self.user_id = user_id
        self.key = f"terminal-sandbox:{team_id}:{user_id}"
        self.redis = get_client()

    @staticmethod
    def _renew_lock(lock: Lock, stopped: Event) -> None:
        while not stopped.wait(60):
            try:
                lock.reacquire()
            except RedisError:
                return

    @contextmanager
    def _acquire_lock(self) -> Iterator[Lock]:
        with self.redis.lock(f"{self.key}:lock", timeout=180, blocking_timeout=0, thread_local=False) as lock:
            stopped = Event()
            renewal = Thread(target=self._renew_lock, args=(lock, stopped), daemon=True)
            renewal.start()
            try:
                yield lock
            finally:
                stopped.set()
                renewal.join()

    def _startup_failure(self, stage: str, **properties: object) -> TerminalSandboxUnavailable:
        # The DRF exception handler does not report APIException, so record the failed stage here.
        capture_exception(
            RuntimeError(f"Terminal sandbox {stage} failed"),
            {"team_id": self.team_id, "stage": stage, **properties},
        )
        return TerminalSandboxUnavailable()

    def start(self, size: str) -> dict[str, str]:
        try:
            with self._acquire_lock() as lock:
                sandbox_class = get_sandbox_class_for_backend("modal")
                existing = self.redis.get(self.key)
                if existing:
                    record = json.loads(existing)
                    try:
                        sandbox = sandbox_class.get_by_id(record["sandbox_id"])
                        if sandbox.is_running() and record["size"] == size:
                            credentials = sandbox.create_preview_connect_credentials(
                                8080, {"team_id": self.team_id, "user_id": self.user_id}
                            )
                            if not credentials.token:
                                raise self._startup_failure("connect token", sandbox_id=sandbox.id)
                            return {
                                "id": record["id"],
                                "url": credentials.url,
                                "token": credentials.token,
                                "sandbox_size": record["size"],
                            }
                        sandbox.destroy()
                    except SandboxNotFoundError:
                        pass
                    self.redis.delete(self.key)
                cpu, memory = SANDBOX_SIZES[size]
                sandbox = sandbox_class.create(
                    SandboxConfig(
                        name=f"terminal-{uuid4()}",
                        template=SandboxTemplate.NOTEBOOK_BASE,
                        cpu_cores=cpu,
                        memory_gb=memory,
                        ttl_seconds=SANDBOX_LIFETIME_SECONDS,
                        environment_variables={"TERMINAL_ORIGIN": settings.SITE_URL.rstrip("/")},
                        metadata={"team_id": str(self.team_id), "user_id": str(self.user_id), "product": "terminal"},
                    )
                )
                try:
                    written = sandbox.write_file(
                        "/tmp/posthog-terminal.py", Path(__file__).with_name("terminal_server.py").read_bytes()
                    )
                    if written.exit_code:
                        raise self._startup_failure("server upload", sandbox_id=sandbox.id, exit_code=written.exit_code)
                    launched = sandbox.execute(
                        "nohup python /tmp/posthog-terminal.py >/tmp/posthog-terminal.log 2>&1 </dev/null & "
                        "for i in $(seq 1 100); do curl -fsS http://127.0.0.1:8080/health >/dev/null && exit 0; sleep 0.1; done; exit 1",
                        timeout_seconds=15,
                    )
                    if launched.exit_code:
                        raise self._startup_failure("health check", sandbox_id=sandbox.id, exit_code=launched.exit_code)
                    credentials = sandbox.create_preview_connect_credentials(
                        8080, {"team_id": self.team_id, "user_id": self.user_id}
                    )
                    if not credentials.token:
                        raise self._startup_failure("connect token", sandbox_id=sandbox.id)
                    if not lock.owned():
                        raise Throttled(detail="The sandbox start expired. Try again in a moment.")
                    session_id = str(uuid4())
                    self.redis.set(
                        self.key,
                        json.dumps({"id": session_id, "sandbox_id": sandbox.id, "size": size}),
                        ex=SANDBOX_LIFETIME_SECONDS,
                    )
                    return {"id": session_id, "url": credentials.url, "token": credentials.token, "sandbox_size": size}
                except Exception:
                    sandbox.destroy()
                    raise
        except LockError as error:
            raise Throttled(detail="The sandbox is starting or stopping. Try again in a moment.") from error

    def stop(self, session_id: str) -> None:
        try:
            with self._acquire_lock():
                existing = self.redis.get(self.key)
                if not existing:
                    return
                record = json.loads(existing)
                if record["id"] != session_id:
                    raise NotFound()
                try:
                    sandbox = get_sandbox_class_for_backend("modal").get_by_id(record["sandbox_id"])
                    sandbox.destroy()
                except SandboxNotFoundError:
                    pass
                self.redis.delete(self.key)
        except LockError as error:
            raise Throttled(detail="The sandbox is starting or stopping. Try again in a moment.") from error
