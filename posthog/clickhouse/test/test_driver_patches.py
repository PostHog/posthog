import pytest

from django.test import SimpleTestCase

from clickhouse_driver.bufferedreader import BufferedSocketReader
from clickhouse_driver.bufferedwriter import BufferedSocketWriter
from clickhouse_driver.columns.service import get_column_by_spec
from clickhouse_driver.context import Context
from clickhouse_driver.streams import native as native_stream
from parameterized import parameterized

from posthog.clickhouse.driver_patches import ClickHouseColumnDecodeError, install_clickhouse_driver_patches


class FakeSocket:
    def __init__(self, data: bytes = b"") -> None:
        self.data = bytearray(data)
        self.position = 0

    def sendall(self, chunk: bytes) -> None:
        self.data += chunk

    def recv_into(self, view: memoryview) -> int:
        size = min(len(view), len(self.data) - self.position)
        view[:size] = self.data[self.position : self.position + size]
        self.position += size
        return size


def build_context() -> Context:
    context = Context()
    context.settings = {}
    context.client_settings = {"strings_as_bytes": False, "strings_encoding": "utf-8", "use_numpy": False}
    return context


class TestClickHouseDriverPatches(SimpleTestCase):
    def setUp(self) -> None:
        install_clickhouse_driver_patches()
        self.context = build_context()

    @parameterized.expand(
        [
            # Each spec nests a comma before a parenthesis, which the driver's comma regex mis-splits.
            ("nested_map", "Map(String, Map(String, Array(UInt64)))", [{"a": {"x": [1, 2]}}, {}]),
            (
                "tuple_value",
                "Map(String, Tuple(Decimal(10, 2), Nullable(String)))",
                [{"a": (1, "b")}, {"c": (2, None)}],
            ),
            ("map_of_maps", "Map(String, Map(String, Map(String, UInt64)))", [{"a": {"b": {"c": 3}}}]),
            # Shapes the regex already handled, kept so the replacement cannot regress them.
            ("flat_map", "Map(String, String)", [{"a": "b"}]),
            ("decimal_value", "Map(String, Decimal(10, 2))", [{"a": 1}]),
        ]
    )
    def test_map_column_round_trips(self, _name: str, spec: str, rows: list[dict]) -> None:
        socket = FakeSocket()
        writer = BufferedSocketWriter(socket, 1 << 16)
        writing_column = get_column_by_spec(spec, {"context": self.context})
        writing_column.write_state_prefix(writer)
        writing_column.write_data(rows, writer)
        writer.flush()

        reader = BufferedSocketReader(FakeSocket(bytes(socket.data)), 1 << 16)
        reading_column = get_column_by_spec(spec, {"context": self.context})
        reading_column.read_state_prefix(reader)

        assert [dict(row) for row in reading_column.read_data(len(rows), reader)] == rows

    def test_undecodable_column_names_its_type(self) -> None:
        with pytest.raises(ClickHouseColumnDecodeError) as caught:
            native_stream.read_column(self.context, "Map(String, String, String)", 1, None)

        assert caught.value.column_type == "Map(String, String, String)"
