import os
import sys
import subprocess
from pathlib import Path

from unittest import TestCase

from django.core.exceptions import ImproperlyConfigured

from parameterized import parameterized

from posthog.settings.utils import assert_postgres_engine


class TestAssertPostgresEngine(TestCase):
    @parameterized.expand(
        [
            ("django.db.backends.mysql",),
            ("django.db.backends.sqlite3",),
            ("django.db.backends.oracle",),
            ("django_cockroachdb",),
        ]
    )
    def test_raises_on_a_non_postgresql_backend(self, engine):
        with self.assertRaises(ImproperlyConfigured):
            assert_postgres_engine(engine)

    @parameterized.expand(
        [
            ("django.db.backends.postgresql",),
            ("django.db.backends.postgresql_psycopg2",),
            ("django.contrib.gis.db.backends.postgis",),
        ]
    )
    def test_does_not_raise_on_a_postgresql_backend(self, engine):
        assert_postgres_engine(engine)


class TestDatabaseUrlEngine(TestCase):
    def test_a_mysql_database_url_stops_the_settings_import(self):
        # A settings module runs once per process, so the guard can only be reached in a fresh one.
        repo_root = Path(__file__).parents[2]
        result = subprocess.run(
            [sys.executable, "-c", "import posthog.settings.data_stores"],
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
                "PYTHONPATH": str(repo_root),
                "SECRET_KEY": "not-a-real-key",
                "DATABASE_URL": "mysql://posthog:posthog@db:3306/posthog",
            },
            capture_output=True,
            text=True,
            cwd=repo_root,
        )

        assert "requires PostgreSQL" in result.stderr
