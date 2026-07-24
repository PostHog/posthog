from unittest.mock import patch

from django.core.management.commands.migrate import Command as DjangoMigrateCommand
from django.test import SimpleTestCase

from posthog.management.commands.migrate import Command


class TestMigrateCommand(SimpleTestCase):
    def test_unconfigured_database_alias_defers_to_django(self):
        # When the orphan-check and caching paths are skipped (production/test mode), the command
        # must not resolve connections[database] itself. An eager lookup crashes with a misleading
        # asgiref/ConnectionDoesNotExist chain for an unconfigured alias (e.g. --database=default_direct
        # without POSTHOG_POSTGRES_DIRECT_HOST); deferring lets Django raise its own clear error.
        command = Command()
        with patch.object(DjangoMigrateCommand, "handle") as mock_super_handle:
            command.handle(database="default_direct_unconfigured", interactive=False, production=True)
        mock_super_handle.assert_called_once()
