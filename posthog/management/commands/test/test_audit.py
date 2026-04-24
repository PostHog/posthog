from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.management.audit import EVENT_NAME, SAFE_FULL_ARGV_COMMANDS, SKIP_COMMANDS, _redact_argv, run_with_audit


class TestRedactArgv(TestCase):
    @parameterized.expand(
        [
            (
                "long_flag_with_equals_value_redacted",
                ["manage.py", "shell_plus", "--quiet-load=secret"],
                ["--quiet-load=<redacted>"],
                True,
            ),
            (
                "long_flag_with_separate_value_dropped",
                ["manage.py", "shell_plus", "--command", "DROP TABLE users"],
                ["--command"],
                True,
            ),
            (
                "short_flag_kept_value_dropped",
                ["manage.py", "shell_plus", "-c", "print(1)"],
                ["-c"],
                True,
            ),
            (
                "positionals_collapsed",
                ["manage.py", "create_user", "alice", "alice@example.com"],
                ["<2 positional>"],
                True,
            ),
            (
                "mix_of_flags_and_positionals",
                ["manage.py", "backfill", "--batch=50", "team1", "team2"],
                ["--batch=<redacted>", "<2 positional>"],
                True,
            ),
            (
                "allowlisted_command_passes_through",
                ["manage.py", "migrate", "posthog", "0042", "--fake"],
                ["posthog", "0042", "--fake"],
                False,
            ),
            (
                "empty_argv_after_command",
                ["manage.py", "somecommand"],
                [],
                True,
            ),
        ]
    )
    def test_redact_argv(self, _name, argv, expected_args, expected_was_redacted):
        got_args, got_was_redacted = _redact_argv(argv)
        self.assertEqual(got_args, expected_args)
        self.assertEqual(got_was_redacted, expected_was_redacted)

    def test_all_allowlisted_commands_pass_argv_through(self):
        for command in SAFE_FULL_ARGV_COMMANDS:
            args, was_redacted = _redact_argv(["manage.py", command, "--flag=value", "pos"])
            self.assertFalse(was_redacted, f"{command} should not be redacted")
            self.assertEqual(args, ["--flag=value", "pos"])


class TestRunWithAudit(TestCase):
    def _make_capture_mock(self):
        """Return (patch_context, capture_mock) for ph_scoped_capture."""
        capture_mock = MagicMock()
        scoped_cm = MagicMock()
        scoped_cm.__enter__ = MagicMock(return_value=capture_mock)
        scoped_cm.__exit__ = MagicMock(return_value=False)
        return scoped_cm, capture_mock

    def _run(self, argv, execute_fn, is_cloud=True):
        scoped_cm, capture_mock = self._make_capture_mock()
        with (
            patch("posthog.cloud_utils.is_cloud", return_value=is_cloud),
            patch("posthog.ph_client.ph_scoped_capture", return_value=scoped_cm),
            patch("posthog.utils.get_machine_id", return_value="machine-xyz"),
        ):
            try:
                run_with_audit(execute_fn, argv)
                raised = None
            except BaseException as e:
                raised = e
        return capture_mock, raised

    def test_clean_exit_emits_event_with_zero_exit_code(self):
        execute = MagicMock()
        capture, raised = self._run(["manage.py", "check"], execute)
        self.assertIsNone(raised)
        execute.assert_called_once_with(["manage.py", "check"])
        capture.assert_called_once()
        kwargs = capture.call_args.kwargs
        self.assertEqual(kwargs["event"], EVENT_NAME)
        self.assertEqual(kwargs["distinct_id"], "machine-xyz")
        props = kwargs["properties"]
        self.assertEqual(props["command"], "check")
        self.assertEqual(props["exit_code"], 0)
        self.assertIsNone(props["error_type"])
        self.assertIn("duration_ms", props)
        self.assertIn("hostname", props)

    def test_system_exit_preserves_code_and_reraises(self):
        def execute(_argv):
            raise SystemExit(2)

        capture, raised = self._run(["manage.py", "some_cmd"], execute)
        self.assertIsInstance(raised, SystemExit)
        self.assertEqual(raised.code, 2)
        self.assertEqual(capture.call_args.kwargs["properties"]["exit_code"], 2)

    def test_system_exit_none_code_is_zero(self):
        def execute(_argv):
            raise SystemExit()

        capture, raised = self._run(["manage.py", "some_cmd"], execute)
        self.assertIsInstance(raised, SystemExit)
        self.assertEqual(capture.call_args.kwargs["properties"]["exit_code"], 0)

    def test_unhandled_exception_records_error_type_and_reraises(self):
        def execute(_argv):
            raise ValueError("boom")

        capture, raised = self._run(["manage.py", "some_cmd"], execute)
        self.assertIsInstance(raised, ValueError)
        props = capture.call_args.kwargs["properties"]
        self.assertEqual(props["exit_code"], 1)
        self.assertEqual(props["error_type"], "ValueError")

    def test_telemetry_failure_does_not_break_command(self):
        execute = MagicMock()
        with (
            patch("posthog.cloud_utils.is_cloud", return_value=True),
            patch("posthog.ph_client.ph_scoped_capture", side_effect=RuntimeError("network down")),
            patch("posthog.utils.get_machine_id", return_value="machine-xyz"),
        ):
            run_with_audit(execute, ["manage.py", "check"])
        execute.assert_called_once()

    def test_no_event_when_not_cloud(self):
        execute = MagicMock()
        capture, raised = self._run(["manage.py", "check"], execute, is_cloud=False)
        self.assertIsNone(raised)
        capture.assert_not_called()

    @parameterized.expand(sorted(SKIP_COMMANDS))
    def test_no_event_for_skipped_command(self, skipped_command):
        argv = ["manage.py", skipped_command] if skipped_command else ["manage.py"]
        execute = MagicMock()
        capture, raised = self._run(argv, execute)
        self.assertIsNone(raised)
        capture.assert_not_called()

    def test_no_event_for_missing_command(self):
        execute = MagicMock()
        capture, raised = self._run(["manage.py"], execute)
        self.assertIsNone(raised)
        capture.assert_not_called()
