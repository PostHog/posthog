from io import StringIO

from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase


class TestAnalyzeMigrationRisk(TestCase):
    def test_check_missing_migrations_when_none_needed(self):
        """Should return empty string when no migrations are needed."""
        from posthog.management.commands.analyze_migration_risk import Command

        command = Command()

        with patch("django.db.migrations.autodetector.MigrationAutodetector") as mock_autodetector:
            mock_autodetector.return_value.changes.return_value = {}
            result = command.check_missing_migrations()

        assert result == ""

    def test_check_missing_migrations_when_needed(self):
        """Should return warning when migrations are needed."""
        from posthog.management.commands.analyze_migration_risk import Command

        command = Command()

        # Create mock migration with operations
        mock_migration = MagicMock()
        mock_operation = MagicMock()
        mock_operation.describe.return_value = "Remove field test_field from testmodel"
        mock_migration.operations = [mock_operation]

        with patch("django.db.migrations.autodetector.MigrationAutodetector") as mock_autodetector:
            mock_autodetector.return_value.changes.return_value = {"posthog": [mock_migration]}
            result = command.check_missing_migrations()

        assert "MISSING MIGRATIONS DETECTED" in result
        assert "makemigrations" in result
        assert "Remove field test_field from testmodel" in result

    def test_check_missing_migrations_handles_errors(self):
        """Should return empty string on other errors."""
        from posthog.management.commands.analyze_migration_risk import Command

        command = Command()

        with patch("django.db.migrations.loader.MigrationLoader") as mock_loader:
            mock_loader.side_effect = Exception("Database error")
            result = command.check_missing_migrations()

        assert result == ""

    def test_command_outputs_missing_migration_warning(self):
        """Should output missing migration warning when detected."""
        import sys
        from io import StringIO

        # Capture stdout since the command uses print()
        captured_output = StringIO()
        old_stdout = sys.stdout

        try:
            sys.stdout = captured_output

            # Create mock migration with operations
            mock_migration = MagicMock()
            mock_operation = MagicMock()
            mock_operation.describe.return_value = "Remove field test_field from testmodel"
            mock_migration.operations = [mock_operation]

            with patch(
                "posthog.management.commands.analyze_migration_risk.Command.get_unapplied_migrations"
            ) as mock_get:
                mock_get.return_value = []

                with patch("django.db.migrations.autodetector.MigrationAutodetector") as mock_autodetector:
                    mock_autodetector.return_value.changes.return_value = {"posthog": [mock_migration]}
                    call_command("analyze_migration_risk")

            output = captured_output.getvalue()
            assert "MISSING MIGRATIONS DETECTED" in output
        finally:
            sys.stdout = old_stdout

    def test_command_silent_when_no_migrations_and_no_missing(self):
        """Should output nothing when no migrations and no missing migrations."""
        out = StringIO()

        with patch("posthog.management.commands.analyze_migration_risk.Command.get_unapplied_migrations") as mock_get:
            mock_get.return_value = []

            with patch("django.db.migrations.autodetector.MigrationAutodetector") as mock_autodetector:
                mock_autodetector.return_value.changes.return_value = {}
                call_command("analyze_migration_risk", stdout=out)

        output = out.getvalue()
        assert output == ""
