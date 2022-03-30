import datetime
import unittest

from posthog.storage.object_storage import dump_test_file, get_test_file


class TestWeCanUseStorage(unittest.TestCase):
    def test_can_we(self):
        file_name = f"test{datetime.datetime.now()}"
        dump_test_file(file_name)
        self.assertIsNotNone(get_test_file(file_name))
