import os
import unittest
import uuid

from posthog.storage.object_storage import list_files, read, write

large_file = str(os.urandom(10 * 1024 * 1024))


def write_a_chunk(chunk_index: int, session_id: str) -> str:
    chunk_id = uuid.uuid4()
    file_name = f"{session_id}/{chunk_index}-{chunk_id}"
    write(file_name, large_file)
    return file_name


class TestStorage(unittest.TestCase):
    def test_write_to_a_subfolder(self):
        file_name = write_a_chunk(0, str(uuid.uuid4()))
        self.assertIsNotNone(read(file_name))

    def test_write_two_files_and_read_in_order_when_written_in_order(self):
        session_id = str(uuid.uuid4())
        write_a_chunk(0, session_id)
        write_a_chunk(1, session_id)
        listed = list_files(session_id)
        files = [s[0] for s in listed]
        self.assertEqual(files, ["0", "1"])

    def test_write_two_files_and_read_in_order_when_written_out_of_order(self):
        session_id = str(uuid.uuid4())
        write_a_chunk(1, session_id)
        write_a_chunk(0, session_id)
        listed = list_files(session_id)
        files = [s[0] for s in listed]
        self.assertEqual(files, ["0", "1"])
