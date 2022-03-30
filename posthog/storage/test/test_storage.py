import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytz

from posthog.storage.object_storage import delete, read, write


def write_a_chunk(chunk_index: int, session_id: str, content: str) -> str:
    chunk_id = uuid.uuid4()
    file_name = f"{session_id}/{chunk_index}-{chunk_id}"
    write(file_name, content)
    return file_name


class TestStorage(unittest.TestCase):
    def test_write_and_read_works_with_known_content(self):
        file_name = write_a_chunk(chunk_index=0, session_id=str(uuid.uuid4()), content="my content")
        self.assertEqual(read(file_name), "my content")

    @patch("posthog.storage.object_storage.list_all")
    def test_deleting_old_files(self, list_all):
        old_mock_storage_object = Mock()
        old_mock_storage_object.last_modified = pytz.UTC.localize(datetime.now() - timedelta(days=31))

        fresh_mock_storage_object = Mock()
        fresh_mock_storage_object.last_modified = pytz.UTC.localize(datetime.now() - timedelta(days=28))

        list_all.return_value = [old_mock_storage_object, fresh_mock_storage_object]

        thirty_days_ago = datetime.now() - timedelta(days=30)

        deleted_count = delete(thirty_days_ago)

        self.assertEqual(deleted_count, 1)
        old_mock_storage_object.delete.assert_called_once()
        fresh_mock_storage_object.delete.assert_not_called()
