import datetime
import os
import unittest

from posthog.storage.object_storage import read, write


class TestWeCanUseStorage(unittest.TestCase):
    def test_can_we(self):
        file_name = f"test{datetime.datetime.now()}"
        write(file_name, str(os.urandom(10 * 1024 * 1024)))
        self.assertIsNotNone(read(file_name))
