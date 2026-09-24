from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from fakeredis import FakeRedis
from parameterized import parameterized
from rest_framework.exceptions import NotFound, Throttled

from posthog.api.services.terminal import TerminalSandboxService, TerminalSandboxUnavailable
from posthog.api.terminal import TerminalSandboxRequestSerializer
from posthog.models import Organization, Team


class TestTerminalSandboxService(SimpleTestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        redis_patch = patch("posthog.api.services.terminal.get_client", return_value=self.redis)
        redis_patch.start()
        self.addCleanup(redis_patch.stop)
        provider_patch = patch("posthog.api.services.terminal.get_sandbox_class_for_backend")
        self.provider = provider_patch.start().return_value
        self.addCleanup(provider_patch.stop)
        self.sandbox = MagicMock()
        self.sandbox.id = "sb-test-terminal"
        self.sandbox.write_file.return_value.exit_code = 0
        self.sandbox.execute.return_value.exit_code = 0
        self.sandbox.create_preview_connect_credentials.return_value = SimpleNamespace(
            url="https://terminal.example.com", token="fake-sandbox-connect-token"
        )
        self.provider.create.return_value = self.sandbox
        self.provider.get_by_id.return_value = self.sandbox
        self.service = TerminalSandboxService(team_id=1, user_id=2)

    @parameterized.expand([("small", 1, 2), ("high_memory", 8, 32)])
    def test_provisions_selected_notebook_image_shape_and_reuses_it(self, size: str, cpu: int, memory: int) -> None:
        session = self.service.start(size)
        config = self.provider.create.call_args.args[0]
        assert config.template == "notebook_base"
        assert (config.cpu_cores, config.memory_gb, config.ttl_seconds) == (cpu, memory, 3600)
        assert config.metadata == {"team_id": "1", "user_id": "2", "product": "terminal"}
        assert self.service.start(size) == session
        assert self.provider.create.call_count == 1
        self.service.stop(session["id"])
        self.sandbox.destroy.assert_called_once()
        self.service.stop(session["id"])
        self.sandbox.destroy.assert_called_once()

    def test_changing_size_replaces_the_existing_sandbox(self) -> None:
        first = self.service.start("small")
        second = self.service.start("large")
        assert first["id"] != second["id"]
        assert second["sandbox_size"] == "large"
        self.sandbox.destroy.assert_called_once()
        assert self.provider.create.call_count == 2
        with self.assertRaises(NotFound):
            self.service.stop(first["id"])
        assert self.sandbox.destroy.call_count == 1

    @parameterized.expand([(1, 3), (2, 2)])
    def test_sessions_are_scoped_to_project_and_owner(self, team_id: int, user_id: int) -> None:
        session = self.service.start("small")
        other = TerminalSandboxService(team_id=team_id, user_id=user_id)
        other.stop(session["id"])
        self.sandbox.destroy.assert_not_called()
        other_session = other.start("small")
        assert other_session["id"] != session["id"]
        assert self.provider.create.call_count == 2

    def test_failed_start_destroys_sandbox_and_can_retry(self) -> None:
        self.sandbox.execute.return_value.exit_code = 1
        with self.assertRaises(TerminalSandboxUnavailable):
            self.service.start("small")
        self.sandbox.destroy.assert_called_once()
        self.sandbox.execute.return_value.exit_code = 0
        assert self.service.start("small")["id"]
        assert self.provider.create.call_count == 2

    def test_concurrent_starts_do_not_provision_another_sandbox(self) -> None:
        with self.redis.lock("terminal-sandbox:1:2:lock"):
            with self.assertRaises(Throttled):
                self.service.start("small")
        self.provider.create.assert_not_called()

    def test_lost_provisioning_lock_destroys_the_untracked_sandbox(self) -> None:
        def lose_lock(*args: object, **kwargs: object) -> SimpleNamespace:
            self.redis.delete("terminal-sandbox:1:2:lock")
            return SimpleNamespace(exit_code=0)

        self.sandbox.execute.side_effect = lose_lock
        with self.assertRaises(Throttled):
            self.service.start("small")
        self.sandbox.destroy.assert_called_once()
        assert not self.redis.exists(self.service.key)

    def test_failed_stop_preserves_session_for_retry(self) -> None:
        session = self.service.start("small")
        self.sandbox.destroy.side_effect = RuntimeError("Provider unavailable")
        with self.assertRaises(RuntimeError):
            self.service.stop(session["id"])
        self.sandbox.destroy.side_effect = None
        self.service.stop(session["id"])
        assert self.sandbox.destroy.call_count == 2

    @parameterized.expand([("huge",), (None,)])
    def test_rejects_unsupported_sizes(self, size: str | None) -> None:
        serializer = TerminalSandboxRequestSerializer(data={"sandbox_size": size})
        assert not serializer.is_valid()
        assert "sandbox_size" in serializer.errors


class TestTerminalAPI(APIBaseTest):
    def test_validates_size_and_requires_the_terminal_flag(self) -> None:
        with patch("posthog.api.terminal.feature_enabled_or_false", return_value=False):
            response = self.client.post(f"/api/projects/{self.team.pk}/terminal/", {"sandbox_size": "huge"})
            assert response.status_code == 400
            response = self.client.post(f"/api/projects/{self.team.pk}/terminal/", {"sandbox_size": "small"})
            assert response.status_code == 403

    def test_cannot_start_a_sandbox_in_another_organization(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        with patch("posthog.api.services.terminal.get_sandbox_class_for_backend") as provider:
            response = self.client.post(f"/api/projects/{other_team.pk}/terminal/", {"sandbox_size": "small"})
        assert response.status_code in (403, 404)
        provider.assert_not_called()
