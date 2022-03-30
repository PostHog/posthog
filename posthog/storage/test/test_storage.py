import unittest
import uuid

from posthog.storage.object_storage import read, write


def write_a_chunk(chunk_index: int, session_id: str, content: str) -> str:
    chunk_id = uuid.uuid4()
    file_name = f"{session_id}/{chunk_index}-{chunk_id}"
    write(file_name, content)
    return file_name


class TestStorage(unittest.TestCase):
    def test_write_and_read_works_with_known_content(self):
        file_name = write_a_chunk(chunk_index=0, session_id=str(uuid.uuid4()), content="my content")
        self.assertEqual(read(file_name), "my content")
