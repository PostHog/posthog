import json
import tempfile
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import InterfaceError, OperationalError
from django.test import override_settings

import requests
import structlog
from celery.app.task import Task
from celery.exceptions import Retry
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.integrations.backend.fake_backend import FakeBackend
from posthog.integrations.mirror.snapshot import read_snapshot
from posthog.integrations.mirror.tasks import MAX_RETRIES, mirror_integration_row
from posthog.integrations.test.credentials_service_stub import CredentialsServiceStub, StubError, write_signing_key
from posthog.models.integration import Integration

URL = "http://credentials-service.test"
SECRET = "fake-secret-value-never-logged"
LOST_RACE = {"outcome": "conflict", "code": "concurrent_write"}


def _metric(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestMirrorIntegrationRowTask(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        key_path, public_key = write_signing_key(directory.name)
        settings_override = override_settings(
            CREDENTIALS_SERVICE_URL=URL, CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH=key_path
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.stub = CredentialsServiceStub(FakeBackend(), public_key)
        session_patch = patch("posthog.integrations.backend.service_transport.internal_requests", self.stub)
        session_patch.start()
        self.addCleanup(session_patch.stop)
        # An eager retry runs inline. With propagation on, the second retry raises `Retry` out of the test.
        conf = mirror_integration_row._get_app().conf
        self.addCleanup(conf.__setitem__, "task_eager_propagates", conf.get("task_eager_propagates"))
        conf["task_eager_propagates"] = False

    def _row(self, **fields: Any) -> Integration:
        return Integration.objects.create(
            team=self.team, **{"kind": "slack", "sensitive_config": {"access_token": SECRET}, **fields}
        )

    def _run(self, legacy_id: int, *, retries: int = 0, team_gone: bool = False, deleted: bool = False) -> None:
        kwargs = {
            "team_id": self.team.id,
            "kind": "slack",
            "legacy_id": legacy_id,
            "deleted": deleted,
            "team_gone": team_gone,
            "committed_at": "2026-01-01T00:00:00+00:00",
        }
        result = mirror_integration_row.apply(kwargs=kwargs, retries=retries, throw=False)
        assert result.successful(), result.traceback

    def _sent_rows(self) -> list[dict[str, Any]]:
        return [row for body in self.stub.mirror_bodies for row in body["rows"]]

    def test_mirrors_the_current_row(self) -> None:
        row = self._row(integration_id="T1", config={"team": "Example"})

        self._run(row.id)

        [body] = self.stub.mirror_bodies
        assert (body["origin"], body["force"]) == ("write", False)
        stored = self.stub.mirrored[row.id]
        assert (stored["owner"], stored["integration_id"], stored["sensitive_config"]) == (
            self.team.id,
            "T1",
            {"access_token": SECRET},
        )

    @parameterized.expand(
        [
            ("row_gone", False, True),
            ("team_gone", True, False),
        ]
    )
    def test_delete_sends_a_tombstone_unless_the_team_is_gone(
        self, _name: str, team_gone: bool, tombstone: bool
    ) -> None:
        row = self._row()
        legacy_id = row.id
        row.delete()

        self._run(legacy_id, team_gone=team_gone, deleted=True)

        assert self._sent_rows() == [{"legacy_id": legacy_id, "deleted": True, "kind": "slack", "tombstone": tombstone}]

    def test_does_nothing_without_a_service_url(self) -> None:
        row = self._row()
        failed_before = _metric("integrations_mirror_rows_total", kind="slack", outcome="failed")

        with override_settings(CREDENTIALS_SERVICE_URL=""), structlog.testing.capture_logs() as logs:
            self._run(row.id)

        assert self.stub.calls == []
        assert logs == []
        assert _metric("integrations_mirror_rows_total", kind="slack", outcome="failed") == failed_before

    @parameterized.expand(
        [
            ("unavailable_service", requests.Timeout(), None, "unavailable"),
            ("database_failover", None, OperationalError("server closed the connection"), "database"),
            ("database_connection_gone", None, InterfaceError("connection already closed"), "database"),
        ]
    )
    def test_a_retry_after_a_transient_failure_mirrors_the_row(
        self, _name: str, service_failure: Exception | None, database_failure: Exception | None, reason: str
    ) -> None:
        row = self._row()
        if service_failure is not None:
            self.stub.failures = [service_failure]
        database_failures = [database_failure] if database_failure is not None else []

        def flaky_read(**kwargs: Any) -> Any:
            if database_failures:
                raise database_failures.pop()
            return read_snapshot(**kwargs)

        retries_before = _metric("integrations_mirror_task_retries_total", reason=reason)

        with patch("posthog.integrations.mirror.tasks.read_snapshot", side_effect=flaky_read):
            self._run(row.id)

        assert [body["origin"] for body in self.stub.mirror_bodies] == ["retry"]
        assert self.stub.mirrored[row.id]["deleted"] is False
        assert _metric("integrations_mirror_task_retries_total", reason=reason) == retries_before + 1

    @parameterized.expand(
        [
            ("unavailable", lambda stub, legacy_id: setattr(stub, "failures", [requests.Timeout()]), "unavailable"),
            (
                "lost_race",
                lambda stub, legacy_id: stub.mirror_answers.update({legacy_id: [LOST_RACE]}),
                "concurrent_write",
            ),
            (
                "rejected",
                lambda stub, legacy_id: stub.mirror_answers.update(
                    {legacy_id: [{"outcome": "rejected", "code": "forbidden_kind"}]}
                ),
                None,
            ),
            (
                "key_held_outside_the_mirror",
                lambda stub, legacy_id: stub.mirror_answers.update(
                    {legacy_id: [{"outcome": "conflict", "conflicting_legacy_id": None}]}
                ),
                None,
            ),
            (
                "key_held_by_a_mirrored_row",
                lambda stub, legacy_id: stub.mirror_answers.update(
                    {legacy_id: [{"outcome": "conflict", "conflicting_legacy_id": legacy_id + 1000}] * 2}
                ),
                "key_conflict",
            ),
            (
                "undocumented_answer",
                lambda stub, legacy_id: stub.mirror_answers.update({legacy_id: [{"outcome": "merged"}]}),
                None,
            ),
            ("service_refused_the_request", lambda stub, legacy_id: setattr(stub, "_authorize", _refuse), None),
        ]
    )
    def test_retries_only_an_unavailable_service_and_a_lost_race(
        self, _name: str, fail: Any, retry_reason: str | None
    ) -> None:
        row = self._row()
        fail(self.stub, row.id)
        reasons = ("unavailable", "concurrent_write", "key_conflict")
        give_ups_before = {
            reason: _metric("integrations_mirror_task_give_ups_total", reason=reason) for reason in reasons
        }
        retries_before = {
            reason: _metric("integrations_mirror_task_retries_total", reason=reason) for reason in reasons
        }

        # The last attempt: a retryable failure gives up instead of retrying again.
        self._run(row.id, retries=MAX_RETRIES)

        for reason in reasons:
            assert _metric("integrations_mirror_task_give_ups_total", reason=reason) == give_ups_before[reason] + (
                1 if reason == retry_reason else 0
            )
            assert _metric("integrations_mirror_task_retries_total", reason=reason) == retries_before[reason]

    @parameterized.expand(
        [
            ("holder_repaired", False, ["write", "write", "repair", "write"]),
            # The lost race on the holder retries the task, which repairs the holder again.
            ("holder_lost_a_race", True, ["write", "write", "repair", "retry", "repair", "retry"]),
        ]
    )
    def test_key_conflict_mirrors_the_holder_first(
        self, _name: str, holder_loses_race: bool, origins: list[str]
    ) -> None:
        holder = self._row(integration_id="T1")
        self._run(holder.id)
        Integration.objects.filter(pk=holder.pk).update(integration_id="T2")
        row = self._row(integration_id="T1")
        if holder_loses_race:
            self.stub.mirror_answers[holder.id] = [LOST_RACE]

        self._run(row.id)

        assert [body["origin"] for body in self.stub.mirror_bodies] == origins
        assert self.stub.mirrored[holder.id]["integration_id"] == "T2"
        assert self.stub.mirrored[row.id]["integration_id"] == "T1"

    def test_key_conflict_left_after_the_repair_retries_the_task(self) -> None:
        row = self._row(integration_id="T1")
        missing_holder = row.id + 1000
        conflict = {"outcome": "conflict", "conflicting_legacy_id": missing_holder}
        self.stub.mirror_answers[row.id] = [conflict, conflict]
        retries_before = _metric("integrations_mirror_task_retries_total", reason="key_conflict")

        self._run(row.id)

        assert [sent["legacy_id"] for sent in self._sent_rows()] == [row.id, missing_holder, row.id, row.id]
        # The holder is gone from Django, so its copy becomes a tombstone.
        assert self.stub.mirrored[missing_holder]["deleted"] is True
        assert self.stub.mirrored[row.id]["deleted"] is False
        assert _metric("integrations_mirror_task_retries_total", reason="key_conflict") == retries_before + 1

    def test_key_conflict_with_a_chain_of_moved_keys_resolves_on_a_later_attempt(self) -> None:
        first = self._row(integration_id="X")
        second = self._row(integration_id="Y")
        self._run(first.id)
        self._run(second.id)
        Integration.objects.filter(pk=second.pk).update(integration_id="Z")
        Integration.objects.filter(pk=first.pk).update(integration_id="Y")
        third = self._row(integration_id="X")
        kwargs = {"team_id": self.team.id, "kind": "slack", "deleted": False, "team_gone": False}

        # The repair of `first` conflicts with the stale copy of `second`, so this attempt asks for a retry.
        with patch.object(mirror_integration_row, "retry", side_effect=Retry()):
            result = mirror_integration_row.apply(kwargs={**kwargs, "legacy_id": third.id}, throw=False)
        assert result.state == "RETRY"
        assert third.id not in self.stub.mirrored

        # The task of `first` repairs `second`, then the retry of `third` succeeds.
        self._run(first.id)
        self._run(third.id, retries=1)

        assert {
            legacy_id: self.stub.mirrored[legacy_id]["integration_id"] for legacy_id in (first.id, second.id, third.id)
        } == {
            first.id: "Y",
            second.id: "Z",
            third.id: "X",
        }

    def test_no_secret_in_logs_or_retried_task_arguments(self) -> None:
        row = self._row(integration_id="T1", config={"team": "Example"})
        self.stub.mirror_answers[row.id] = [LOST_RACE, {"outcome": "rejected", "code": "validation"}]
        signatures = []
        signature_from_request = Task.signature_from_request

        def capture(task: Task, *args: Any, **kwargs: Any) -> Any:
            signature = signature_from_request(task, *args, **kwargs)
            signatures.append(signature)
            return signature

        with structlog.testing.capture_logs() as logs, patch.object(Task, "signature_from_request", capture):
            self._run(row.id)
            self.stub.failures = [requests.Timeout()]
            self._run(row.id, retries=MAX_RETRIES)
            self.stub.mirror_answers[row.id] = [{"outcome": "merged"}]
            self._run(row.id)

        assert {log["event"] for log in logs} >= {
            "integration_mirror_refused",
            "integration_mirror_gave_up",
            "integration_mirror_failed",
        }
        assert SECRET not in json.dumps(logs, default=str)
        assert signatures
        assert SECRET not in json.dumps([(signature.args, signature.kwargs) for signature in signatures], default=str)


def _refuse(*args: Any, **kwargs: Any) -> Any:
    raise StubError("forbidden_op")
