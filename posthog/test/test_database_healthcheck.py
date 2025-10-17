from freezegun import freeze_time
from unittest import mock

from django.test import TestCase

from posthog.database_healthcheck import DatabaseHealthcheck


class TestDatabaseHealthcheck(TestCase):
    def setUp(self) -> None:
        self.healthcheck = DatabaseHealthcheck(30)
        return super().setUp()

    def test_healthcheck(self):
        self.healthcheck.is_postgres_connected_check = mock.MagicMock(return_value=True)  # type: ignore

        with freeze_time("2021-01-01T00:00:00Z") as frozen_time:
            self.assertTrue(self.healthcheck.is_connected())
            self.assertEqual(self.healthcheck.hits, 0)
            self.assertEqual(self.healthcheck.misses, 1)
            self.assertEqual(self.healthcheck.last_check, 53648640)
            self.healthcheck.is_postgres_connected_check.assert_called_once()

            self.assertTrue(self.healthcheck.is_connected())
            self.assertEqual(self.healthcheck.hits, 1)
            self.assertEqual(self.healthcheck.misses, 1)
            self.assertEqual(self.healthcheck.last_check, 53648640)

            self.assertTrue(self.healthcheck.is_connected())
            self.assertEqual(self.healthcheck.hits, 2)
            self.assertEqual(self.healthcheck.misses, 1)
            self.assertEqual(self.healthcheck.last_check, 53648640)
            self.healthcheck.is_postgres_connected_check.assert_called_once()

            self.healthcheck.is_postgres_connected_check.reset_mock()
            # 30 seconds later
            frozen_time.tick(delta=30)  # type: ignore

            self.assertTrue(self.healthcheck.is_connected())
            self.healthcheck.is_postgres_connected_check.assert_called_once()
            self.assertEqual(self.healthcheck.hits, 2)
            self.assertEqual(self.healthcheck.misses, 2)
            self.assertEqual(self.healthcheck.last_check, 53648641)

            # 30 seconds later
            frozen_time.tick(delta=30)  # type: ignore
            self.healthcheck.is_postgres_connected_check = mock.MagicMock(return_value=False)  # type: ignore

            self.assertFalse(self.healthcheck.is_connected())
            self.assertEqual(self.healthcheck.hits, 2)
            self.assertEqual(self.healthcheck.misses, 3)
            self.assertEqual(self.healthcheck.last_check, 53648642)

    def test_set_is_connected(self):
        self.healthcheck.is_postgres_connected_check = mock.MagicMock(return_value=True)  # type: ignore

        with freeze_time("2021-01-01T00:00:00Z") as frozen_time:
            self.healthcheck.set_connection(True)

            self.assertTrue(self.healthcheck.is_connected())
            self.healthcheck.is_postgres_connected_check.assert_not_called()
            self.assertEqual(self.healthcheck.hits, 1)
            self.assertEqual(self.healthcheck.misses, 0)
            self.assertEqual(self.healthcheck.last_check, 53648640)

            self.healthcheck.set_connection(False)

            self.assertFalse(self.healthcheck.is_connected())
            self.healthcheck.is_postgres_connected_check.assert_not_called()
            self.assertEqual(self.healthcheck.hits, 1)
            self.assertEqual(self.healthcheck.misses, 0)
            self.assertEqual(self.healthcheck.last_check, 53648640)

            # 30 seconds later
            frozen_time.tick(delta=30)  # type: ignore

            self.assertTrue(self.healthcheck.is_connected())
            self.healthcheck.is_postgres_connected_check.assert_called_once()

            self.assertEqual(self.healthcheck.hits, 1)
            self.assertEqual(self.healthcheck.misses, 1)
            self.assertEqual(self.healthcheck.last_check, 53648641)
