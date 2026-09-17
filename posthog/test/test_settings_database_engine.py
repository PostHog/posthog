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
