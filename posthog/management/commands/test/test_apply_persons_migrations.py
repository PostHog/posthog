from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from posthog.management.commands.apply_persons_migrations import _is_no_transaction

MIGRATIONS_DIR = Path(settings.BASE_DIR) / "rust" / "persons_migrations"


class TestNoTransactionMigrations(SimpleTestCase):
    def test_concurrent_index_migrations_opt_out_of_the_transaction(self):
        # CREATE INDEX CONCURRENTLY fails inside a transaction block, so a file
        # that uses it must carry the header both runners read.
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            sql_content = sql_file.read_text()
            if "CONCURRENTLY" not in sql_content:
                continue
            self.assertTrue(
                _is_no_transaction(sql_content),
                f"{sql_file.name} runs CONCURRENTLY but does not start with the no-transaction header",
            )
