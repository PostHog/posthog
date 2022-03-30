import time
import unittest
import uuid
from datetime import datetime, timedelta

from posthog.storage.object_storage import delete, read, write


class TestStorage(unittest.TestCase):
    @classmethod
    def teardown_class(cls):
        """
        Delete the test_bucket after all of the tests are finished
        """
        delete(datetime.now(), "test_bucket")

    def test_write_and_read_works_with_known_content(self):
        session_id = str(uuid.uuid4())
        chunk_id = uuid.uuid4()
        name = f"{session_id}/{0}-{chunk_id}"
        file_name = f"test_bucket/test_write_and_read_works_with_known_content/{name}"
        write(file_name, "my content")
        self.assertEqual(read(file_name), "my content")

    def test_deleting_old_files(self):
        # can't write files frozen to thirty days ago because boto won't let us write files when clock appears skewed
        write("test_bucket/test_deleting_old_files/2 seconds ago", "test")
        time.sleep(1)
        write("test_bucket/test_deleting_old_files/1 second ago ", "test")
        time.sleep(1)
        write("test_bucket/test_deleting_old_files/now", "test")

        one_second_ago = datetime.now() - timedelta(seconds=1)

        deleted_count = delete(one_second_ago, prefix="test_bucket/test_deleting_old_files")

        self.assertEqual(deleted_count, 2)  # does not delete the "now" file
