from unittest import TestCase

from django.core.exceptions import ImproperlyConfigured

from parameterized import parameterized

from posthog.settings.utils import resolve_clickhouse_database


class TestResolveClickhouseDatabase(TestCase):
    def test_test_run_uses_test_db(self):
        result = resolve_clickhouse_database(env_value=None, test=True, test_db="posthog_test", is_collect_static=False)
        self.assertEqual(result, "posthog_test")

    def test_explicit_env_value_wins(self):
        result = resolve_clickhouse_database(
            env_value="posthog", test=False, test_db="posthog_test", is_collect_static=False
        )
        self.assertEqual(result, "posthog")

    def test_collectstatic_falls_back_without_env(self):
        result = resolve_clickhouse_database(env_value=None, test=False, test_db="posthog_test", is_collect_static=True)
        self.assertEqual(result, "default")

    @parameterized.expand([("none", None), ("empty", "")])
    def test_raises_when_unset_outside_test_and_collectstatic(self, _name, env_value):
        with self.assertRaises(ImproperlyConfigured):
            resolve_clickhouse_database(
                env_value=env_value, test=False, test_db="posthog_test", is_collect_static=False
            )
