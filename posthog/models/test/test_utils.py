from posthog.models.utils import uuid7
from posthog.test.base import BaseTest


class TestUUIDv7(BaseTest):
    def test_has_version_of_7(self):
        self.assertEqual(uuid7().version, 7)
