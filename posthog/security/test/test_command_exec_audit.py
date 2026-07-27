import os
import uuid
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from posthog.test.base import APIBaseTest
from unittest import TestCase, mock, skipUnless

from django.test import override_settings
from django.urls import path

import structlog
from parameterized import parameterized
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.clickhouse.query_tagging import AccessMethod
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.security import command_exec_audit
from posthog.security.command_exec_audit import (
    _REDACTED as _R,
    _is_volume_suppressed,
    _scrub_args,
    _scrub_command_string,
    _summarize_env,
    install,
)


class _ExecProbeView(APIView):
    authentication_classes = [PersonalAPIKeyAuthentication, SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        subprocess.run(["true"], check=True)
        return Response({"ok": True})


# Test-only URLconf so a real request/response cycle can run a command from a view.
urlpatterns = [path("api/_exec_audit_probe/", _ExecProbeView.as_view())]


class TestCommandExecAuditScrubbing(TestCase):
    @parameterized.expand(
        [
            ("no_secrets", ["ls", "-la", "/tmp"], ["ls", "-la", "/tmp"]),
            ("flag_value_pair", ["mycli", "--password", "hunter2"], ["mycli", "--password", _R]),
            ("flag_equals", ["mycli", "--api-key=abc123"], ["mycli", f"--api-key={_R}"]),
            ("bare_secret", ["mycli", "my_secret_token"], ["mycli", _R]),
            (
                "value_then_flag_not_consumed",
                ["mycli", "--token", "--verbose"],
                ["mycli", "--token", _R],
            ),
            # "auth" must not over-match common non-secret flags like git's --author.
            ("author_not_redacted", ["git", "log", "--author=Jane"], ["git", "log", "--author=Jane"]),
            # A sensitive *path* is fully redacted and must not consume the following token.
            (
                "sensitive_path_does_not_eat_next",
                ["openssl", "-in", "/etc/ssl/private_key.pem", "-out", "/tmp/cert.pem"],
                ["openssl", "-in", _R, "-out", "/tmp/cert.pem"],
            ),
        ]
    )
    def test_scrub_args(self, _name: str, args: list[str], expected: list[str]) -> None:
        self.assertEqual(_scrub_args(args), expected)

    def test_scrub_args_truncates(self) -> None:
        result = _scrub_args([f"a{i}" for i in range(200)])
        self.assertEqual(len(result), command_exec_audit._MAX_ARGS + 1)
        self.assertIn("truncated", result[-1])

    def test_scrub_args_truncation_count_correct_for_iterator(self) -> None:
        # A single-pass iterable must still report the right truncated count.
        result = _scrub_args(iter([f"a{i}" for i in range(200)]))
        self.assertEqual(result[-1], f"...(+{200 - command_exec_audit._MAX_ARGS} args truncated)")

    def test_scrub_command_string_redacts_secret(self) -> None:
        self.assertEqual(_scrub_command_string("psql --password supersecret db"), f"psql --password {_R} db")

    def test_base64_payload_is_redacted(self) -> None:
        # A secret written via a b64decode heredoc (as the sandbox does) must not be recoverable.
        import base64

        blob = base64.b64encode(b"GITHUB_TOKEN=ghp_" + b"x" * 64).decode()
        token = f"payload = base64.b64decode('{blob}')"
        scrubbed = _scrub_args([token])[0]
        self.assertNotIn(blob, scrubbed)
        self.assertIn(_R, scrubbed)

    def test_short_alphanumeric_args_are_not_blob_redacted(self) -> None:
        # Ordinary short identifiers/flags must survive — blob redaction targets long runs only.
        self.assertEqual(_scrub_args(["ls", "-la", "abc123DEF456"]), ["ls", "-la", "abc123DEF456"])

    def test_url_userinfo_is_redacted(self) -> None:
        # Credentials in a URL/DSN have no hint word; redact the userinfo segment.
        self.assertEqual(
            _scrub_args(["git", "clone", "https://alice:Xy9Zq0pw@github.com/o/r"]),
            ["git", "clone", f"https://{_R}@github.com/o/r"],
        )

    def test_coerce_str_neutralizes_control_chars(self) -> None:
        # Embedded control chars (e.g. newlines) could forge a second audit line — neutralize them.
        self.assertEqual(command_exec_audit._coerce_str("a\nb\rc\td"), "a b c d")

    def test_summarize_env_redacts_non_allowlisted(self) -> None:
        allowed, redacted = _summarize_env({"PATH": "/usr/bin", "AWS_SECRET_KEY": "xxx", "FOO": "bar"})
        self.assertEqual(allowed, {"PATH": "/usr/bin"})
        self.assertEqual(redacted, 2)

    def test_summarize_env_empty(self) -> None:
        self.assertEqual(_summarize_env(None), (None, 0))

    @parameterized.expand(
        [
            # The high-volume introspection shapes we suppress to keep audit volume sane.
            ("uname_flags", ["uname", "-rs"], False, True),
            ("uname_single_flag", ["uname", "-p"], False, True),
            ("lsb_release", ["lsb_release", "-a"], False, True),
            ("ldd_version", ["ldd", "--version"], False, True),
            ("file_brief", ["file", "-b", "/some/path"], False, True),
            ("ldconfig_print", ["ldconfig", "-p"], False, True),
            ("ldconfig_other_flag", ["ldconfig", "-v"], False, False),
            # Absolute path still matches on basename.
            ("absolute_path_uname", ["/usr/bin/uname", "-rs"], False, True),
            # Anything that isn't the exact suppressed shape must fall through to a full audit entry.
            ("uname_positional_arg", ["uname", "-a", "extra"], False, False),
            ("ldd_on_a_binary", ["ldd", "/bin/ls"], False, False),
            ("file_without_brief", ["file", "/some/path"], False, False),
            ("unknown_binary", ["curl", "-s", "https://x"], False, False),
            # shell=True can chain commands — never suppressed, even for a suppressed-looking program.
            ("shell_string_uname", "uname -rs", True, False),
            ("empty_command", [], False, False),
        ]
    )
    def test_is_volume_suppressed(self, _name: str, command: Any, shell: bool, expected: bool) -> None:
        self.assertEqual(_is_volume_suppressed(command, shell), expected)


class TestCommandExecAuditPatching(TestCase):
    def setUp(self) -> None:
        super().setUp()
        # install() is idempotent and audit-only, so patching the process-global sinks here is safe.
        install()

    def _find(self, logs: Sequence[Mapping[str, Any]], sink: str) -> Mapping[str, Any] | None:
        return next((log for log in logs if log.get("event") == "command_execution" and log.get("sink") == sink), None)

    def test_subprocess_run_is_logged(self) -> None:
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["true"], check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertEqual(entry["command"], ["true"])
        self.assertEqual(entry["binary"], "true")
        self.assertFalse(entry["shell"])

    def test_subprocess_shell_secret_is_scrubbed(self) -> None:
        with structlog.testing.capture_logs() as logs:
            subprocess.run("echo --password hunter2", shell=True, check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertTrue(entry["shell"])
        self.assertNotIn("hunter2", entry["command"])

    def test_volume_suppressed_command_is_not_logged(self) -> None:
        # The high-volume introspection commands are dropped to keep audit volume sane.
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["uname", "-rs"], check=False)
        self.assertIsNone(self._find(logs, "subprocess.Popen"))

    def test_non_suppressed_variant_is_still_logged(self) -> None:
        # A positional operand on an otherwise suppressed program is not the suppressed shape — keep auditing.
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["uname", "-a", "extra"], check=False)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertEqual(entry["command"], ["uname", "-a", "extra"])

    def test_os_system_is_logged(self) -> None:
        with structlog.testing.capture_logs() as logs:
            os.system("true")
        entry = self._find(logs, "os.system")
        assert entry is not None
        self.assertTrue(entry["shell"])

    def test_context_is_attached(self) -> None:
        from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries

        org_id = uuid.uuid4()
        reset_query_tags()
        # user_email is intentionally set here but must NOT be logged — it's PII.
        tag_queries(team_id=42, user_id=7, org_id=org_id, user_email="a@b.com")
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["true"], check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertEqual(entry["team_id"], 42)
        self.assertEqual(entry["user_id"], 7)
        # org_id is a UUID in the tags; it must be stringified for the log.
        self.assertEqual(entry["org_id"], str(org_id))
        self.assertNotIn("user_email", entry)

    def test_cwd_is_logged(self) -> None:
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["true"], cwd="/tmp", check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertEqual(entry["cwd"], "/tmp")

    def test_executable_overrides_binary(self) -> None:
        true_path = shutil.which("true")
        assert true_path is not None
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["ignored"], executable=true_path, check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertEqual(entry["binary"], true_path)

    def test_shell_operators_are_flagged(self) -> None:
        with structlog.testing.capture_logs() as logs:
            subprocess.run("true | cat", shell=True, check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertTrue(entry["has_shell_operators"])

    def test_plain_command_has_no_shell_operator_flag(self) -> None:
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["true"], check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertNotIn("has_shell_operators", entry)

    def test_shell_operators_detected_inside_redacted_token(self) -> None:
        # The operator scan runs on the raw command, so a `$(...)` inside a redacted token
        # (here `--token=...`) is still flagged rather than vanishing with the redaction.
        with structlog.testing.capture_logs() as logs:
            subprocess.run("true --token=$(echo x)", shell=True, check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertTrue(entry["has_shell_operators"])
        self.assertNotIn("echo", entry["command"])

    def test_encoded_blob_redacted_but_flagged(self) -> None:
        # The base64 body must be unrecoverable, yet the entry still signals an encoded payload.
        import base64

        blob = base64.b64encode(b"GITHUB_TOKEN=ghp_" + b"x" * 64).decode()
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["python3", "-c", f"import base64; base64.b64decode('{blob}')"], check=False)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertNotIn(blob, " ".join(entry["command"]))
        self.assertTrue(entry["has_encoded_blob"])

    def test_operator_chars_in_argv_are_not_flagged(self) -> None:
        # shell=False: operator chars inside an arg are literal, not injection — must not flag.
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["echo", "a > b && c"], check=True)
        entry = self._find(logs, "subprocess.Popen")
        assert entry is not None
        self.assertFalse(entry["shell"])
        self.assertNotIn("has_shell_operators", entry)

    def test_audit_does_not_break_command(self) -> None:
        result = subprocess.run(["true"], check=False)
        self.assertEqual(result.returncode, 0)

    def test_command_output_is_preserved(self) -> None:
        # The patched Popen must still pipe stdout back to the caller untouched.
        self.assertEqual(subprocess.check_output(["printf", "hello"]), b"hello")

    @parameterized.expand(
        [
            ("missing_binary", ["this-binary-does-not-exist-9f3a"], {}, FileNotFoundError),
            ("nonzero_with_check", ["false"], {"check": True}, subprocess.CalledProcessError),
        ]
    )
    def test_subprocess_exceptions_propagate(self, _name: str, args: list, kwargs: dict, exc: type) -> None:
        with self.assertRaises(exc):
            subprocess.run(args, **kwargs)

    def test_os_system_returns_exit_status(self) -> None:
        self.assertEqual(os.system("exit 0"), 0)
        self.assertNotEqual(os.system("exit 3"), 0)

    def test_audit_failure_never_breaks_the_command(self) -> None:
        # If the audit path raises, the wrapped command must still run and return normally.
        with mock.patch.object(command_exec_audit, "_context", side_effect=RuntimeError("boom")):
            result = subprocess.run(["true"], check=False)
        self.assertEqual(result.returncode, 0)

    def test_reentrancy_guard_suppresses_nested_audit(self) -> None:
        # While an audit is in progress, a nested exec (e.g. the git shell-out in query
        # tagging) must not emit or recurse back into the patched sink.
        token = command_exec_audit._in_audit.set(True)
        try:
            with structlog.testing.capture_logs() as logs:
                command_exec_audit._emit(component="os", sink="os.system", command="true", shell=True)
            self.assertIsNone(self._find(logs, "os.system"))
        finally:
            command_exec_audit._in_audit.reset(token)

    def test_install_is_idempotent(self) -> None:
        # A second install() must not double-wrap and double-log.
        install()
        with structlog.testing.capture_logs() as logs:
            subprocess.run(["true"], cwd="/", check=True)
        matches = [
            log
            for log in logs
            if log.get("event") == "command_execution"
            and log.get("sink") == "subprocess.Popen"
            and log.get("cwd") == "/"
        ]
        self.assertEqual(len(matches), 1)

    @skipUnless(hasattr(os, "posix_spawn"), "posix_spawn unavailable on this platform")
    def test_posix_spawn_is_logged(self) -> None:
        true_path = shutil.which("true")
        assert true_path is not None
        with structlog.testing.capture_logs() as logs:
            pid = os.posix_spawn(true_path, [true_path], os.environ)
            os.waitpid(pid, 0)
        entry = self._find(logs, "os.posix_spawn")
        assert entry is not None
        self.assertEqual(entry["binary"], true_path)

    def test_fork_exec_wrapper_logs_and_passes_through(self) -> None:
        # fork_exec is the raw C exec primitive — exercise the wrapper directly rather than forking.
        received = {}

        def fake_fork_exec(*args, **kwargs):
            received["called"] = True
            return 4321

        with structlog.testing.capture_logs() as logs:
            result = command_exec_audit._fork_exec_wrapper(fake_fork_exec, None, ([b"/bin/ls", b"-la"],), {})
        self.assertEqual(result, 4321)
        self.assertTrue(received.get("called"))
        entry = self._find(logs, "_posixsubprocess.fork_exec")
        assert entry is not None
        self.assertEqual(entry["command"], ["/bin/ls", "-la"])

    def test_install_wraps_fork_exec(self) -> None:
        # Direct callers of the C primitive (bypassing Popen) must still be audited.
        try:
            import _posixsubprocess
        except ImportError:
            self.skipTest("_posixsubprocess unavailable on this platform")
        import wrapt

        self.assertIsInstance(_posixsubprocess.fork_exec, wrapt.ObjectProxy)


@override_settings(ROOT_URLCONF="posthog.security.test.test_command_exec_audit")
class TestCommandExecAuditRequestCycle(APIBaseTest):
    PROBE = "/api/_exec_audit_probe/"

    def setUp(self) -> None:
        super().setUp()
        install()

    def _probe_log(self, logs: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        return next(
            (log for log in logs if log.get("event") == "command_execution" and log.get("sink") == "subprocess.Popen"),
            None,
        )

    def test_session_request_logs_middleware_context(self) -> None:
        # APIBaseTest auto-logs-in self.user; the middleware should populate user/ip/request context
        # onto the command log without any manual tagging in the view.
        with structlog.testing.capture_logs() as logs:
            response = self.client.get(self.PROBE)
        self.assertEqual(response.status_code, 200)
        entry = self._probe_log(logs)
        assert entry is not None
        self.assertEqual(entry["user_id"], self.user.pk)
        self.assertEqual(entry["kind"], "request")
        self.assertEqual(entry["ip_address"], "127.0.0.1")

    def test_personal_api_key_request_logs_auth_context(self) -> None:
        # Key-based auth tags team_id + access_method during DRF dispatch, before the command runs.
        self.client.logout()
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="probe", user=self.user, secure_value=hash_key_value(value), scopes=["*"])
        with structlog.testing.capture_logs() as logs:
            response = self.client.get(self.PROBE, headers={"authorization": f"Bearer {value}"})
        self.assertEqual(response.status_code, 200)
        entry = self._probe_log(logs)
        assert entry is not None
        self.assertEqual(entry["user_id"], self.user.pk)
        self.assertEqual(entry["team_id"], self.team.pk)
        self.assertEqual(entry["access_method"], AccessMethod.PERSONAL_API_KEY)
        self.assertEqual(entry["ip_address"], "127.0.0.1")

    def test_unauthenticated_request_is_still_logged(self) -> None:
        self.client.logout()
        with structlog.testing.capture_logs() as logs:
            response = self.client.get(self.PROBE)
        self.assertEqual(response.status_code, 200)
        entry = self._probe_log(logs)
        assert entry is not None
        self.assertEqual(entry["command"], ["true"])
        self.assertNotIn("user_id", entry)
