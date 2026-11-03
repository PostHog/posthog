from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from unittest.mock import patch

from posthog.dataclasses import frozen


@frozen
class RecordedMetric:
    name: str
    attributes: dict[str, str]
    value: float


class _Instrument:
    def __init__(self, name: str, attributes: dict[str, str], records: list[RecordedMetric]) -> None:
        self._name = name
        self._attributes = attributes
        self._records = records

    def add(self, value: int) -> None:
        self._records.append(RecordedMetric(name=self._name, attributes=self._attributes, value=value))

    def record(self, value: timedelta) -> None:
        self._records.append(
            RecordedMetric(name=self._name, attributes=self._attributes, value=value.total_seconds() * 1000)
        )


class _Meter:
    def __init__(self, attributes: dict[str, str] | None, records: list[RecordedMetric]) -> None:
        self._attributes = attributes or {}
        self._records = records

    def create_counter(self, name: str, *_args: object) -> _Instrument:
        return _Instrument(name, self._attributes, self._records)

    def create_histogram_timedelta(self, name: str, **_kwargs: object) -> _Instrument:
        return _Instrument(name, self._attributes, self._records)


@contextmanager
def recorded_metrics() -> Iterator[list[RecordedMetric]]:
    """Every platform metric recorded inside the block, captured where it reaches Temporal's meter."""
    records: list[RecordedMetric] = []
    with patch(
        "products.alerts_platform.backend.temporal.metrics.get_metric_meter",
        side_effect=lambda attributes=None: _Meter(attributes, records),
    ):
        yield records
