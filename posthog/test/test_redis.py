from datetime import timedelta
from typing import Any
from unittest.mock import patch

import redis
from django.test import TestCase
from freezegun import freeze_time

from posthog.redis import GoldenRetriever, get_client


class TestGolderRetriever(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.redis: Any = get_client()

    def tearDown(self) -> None:
        self.redis._server.connected = True
        self.redis.flushdb()

    @patch("posthog.redis.logger")
    def test_fetching_default_value_when_disconnected(self, _logger) -> None:
        retriever = GoldenRetriever("somekey")
        self.redis._server.connected = False
        self.assertEqual(retriever.get(), set())

    @patch("posthog.redis.logger")
    def test_fetching_value_changing(self, _logger):
        self.redis.rpush("somekey", 1)
        self.redis.rpush("somekey", 2)

        with freeze_time("2020-01-04T00:00:00Z"):
            retriever = GoldenRetriever("somekey")
            self.assertEqual(retriever.get(), {1, 2})

        with freeze_time("2020-01-04T00:00:30Z"):
            self.redis.rpush("somekey", 3)
            self.assertEqual(retriever.get(), {1, 2})

        with freeze_time("2020-01-04T00:03:00Z"):
            self.assertEqual(retriever.get(), {1, 2, 3})

        with freeze_time("2020-01-04T00:07:00Z"):
            self.redis.rpush("somekey", 4)
            self.redis._server.connected = False
            self.assertEqual(retriever.get(), {1, 2, 3})

    @patch("posthog.redis.logger")
    def test_overrides(self, _logger):
        with freeze_time("2020-01-04T00:00:00Z"):
            retriever = GoldenRetriever("somekey", default={1.2}, frequency=timedelta(seconds=1), typecast=float)

            self.redis._server.connected = False
            self.assertEqual(retriever.get(), {1.2})
            self.redis._server.connected = True

            self.assertEqual(retriever.get(), {1.2})

        with freeze_time("2020-01-04T00:00:02Z"):
            self.assertEqual(retriever.get(), set())

        with freeze_time("2020-01-04T00:00:04Z"):
            self.redis.rpush("somekey", "5.6")
            self.assertEqual(retriever.get(), {5.6})
