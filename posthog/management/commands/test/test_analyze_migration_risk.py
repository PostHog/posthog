from io import StringIO

from unittest.mock import patch

from django.test import TestCase


class TestAnalyzeMigrationRisk(TestCase):
    def test_check_missing_migrations_when_none_needed(self):
        """Should return empty string when no migrations are needed."""
        from posthog.management.commands.analyze_migration_risk import Command

        command = Command()

        with patch("django.core.management.call_command"):
            # No exception means no migrations needed
            result = command.check_missing_migrations()

        assert result == ""

    def test_check_missing_migrations_when_needed(self):
        """Should return warning when migrations are needed."""
        from posthog.management.commands.analyze_migration_risk import Command

        command = Command()

        def mock_makemigrations(*args, **kwargs):
            # Simulate Django's output to stdout
            import sys

            sys.stdout.write("Migrations for 'posthog':\n")
            sys.stdout.write("  posthog/migrations/0001_test.py\n")
            sys.stdout.write("    - Remove field test_field from testmodel\n")
            raise SystemExit(1)

        with patch("django.core.management.call_command", side_effect=mock_makemigrations):
            result = command.check_missing_migrations()

        assert "**Summary:** ⚠️ Missing migrations detected" in result
        assert "makemigrations" in result
        assert "Remove field test_field from testmodel" in result

    def test_check_missing_migrations_handles_errors(self):
        """Should return empty string on other errors."""
        from posthog.management.commands.analyze_migration_risk import Command

        command = Command()

        with patch("django.core.management.call_command") as mock_call_command:
            mock_call_command.side_effect = Exception("Database error")
            result = command.check_missing_migrations()

        assert result == ""

    def test_command_outputs_missing_migration_warning(self):
        """Should output missing migration warning when detected."""
        import sys
        from io import StringIO

        from django.core.management import call_command as real_call_command

        # Capture stdout since the command uses print()
        captured_output = StringIO()
        old_stdout = sys.stdout

        def selective_mock_call_command(command_name, *args, **kwargs):
            if command_name == "makemigrations":
                # Simulate Django's output to stdout
                sys.stdout.write("Migrations for 'posthog':\n")
                sys.stdout.write("  posthog/migrations/0001_test.py\n")
                sys.stdout.write("    - Remove field test_field from testmodel\n")
                raise SystemExit(1)
            else:
                # Call the real command for other commands
                return real_call_command(command_name, *args, **kwargs)

        try:
            sys.stdout = captured_output

            with patch(
                "posthog.management.commands.analyze_migration_risk.Command.get_unapplied_migrations"
            ) as mock_get:
                mock_get.return_value = []

                with patch("django.core.management.call_command", side_effect=selective_mock_call_command):
                    real_call_command("analyze_migration_risk")

            output = captured_output.getvalue()
            assert "**Summary:** ⚠️ Missing migrations detected" in output
        finally:
            sys.stdout = old_stdout

    def test_command_silent_when_no_migrations_and_no_missing(self):
        """Should output nothing when no migrations and no missing migrations."""
        from django.core.management import call_command as real_call_command

        out = StringIO()

        def selective_mock_call_command(command_name, *args, **kwargs):
            if command_name == "makemigrations":
                # No exception means no migrations needed
                return
            else:
                # Call the real command for other commands
                return real_call_command(command_name, *args, **kwargs)

        with patch("posthog.management.commands.analyze_migration_risk.Command.get_unapplied_migrations") as mock_get:
            mock_get.return_value = []

            with patch("django.core.management.call_command", side_effect=selective_mock_call_command):
                real_call_command("analyze_migration_risk", stdout=out)

        output = out.getvalue()
        assert output == ""
