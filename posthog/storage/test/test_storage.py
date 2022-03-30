import unittest
import uuid
from datetime import datetime, timedelta

from posthog.storage.object_storage import delete_older_than, read, write


class TestStorage(unittest.TestCase):
    @classmethod
    def teardown_class(cls):
        """
        Delete the test_bucket after all of the tests are finished
        """
        delete_older_than(datetime.now(), "test_bucket")

    def test_write_and_read_works_with_known_content(self):
        session_id = str(uuid.uuid4())
        chunk_id = uuid.uuid4()
        name = f"{session_id}/{0}-{chunk_id}"
        file_name = f"test_bucket/test_write_and_read_works_with_known_content/{name}"
        write(file_name, "my content")
        self.assertEqual(read(file_name), "my content")

    def test_deleting_old_files(self):
        write("test_bucket/test_deleting_old_files/2014-04-01/very_old", "test")

        thirty_one_days_ago = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d")
        write(f"test_bucket/test_deleting_old_files/{thirty_one_days_ago}/deletable ", "test")

        twenty_nine_days_ago = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
        write(f"test_bucket/test_deleting_old_files/{twenty_nine_days_ago}/not_deletable", "test")

        thirty_days_ago = datetime.now() - timedelta(days=30)

        deleted_count = delete_older_than(thirty_days_ago.date(), prefix="test_bucket/test_deleting_old_files")

        self.assertEqual(deleted_count, 2)  # does not delete the "now" file
