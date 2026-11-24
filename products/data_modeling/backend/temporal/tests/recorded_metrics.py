from collections.abc import Iterator
from contextlib import contextmanager

from unittest.mock import patch

import temporalio.workflow

from posthog.dataclasses import frozen

REQUEST_TO_FINISH_METRIC = "data_modeling_request_to_finish_seconds"


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

    def record(self, value: float) -> None:
        self._records.append(RecordedMetric(name=self._name, attributes=self._attributes, value=value))


class _Meter:
    def __init__(self, attributes: dict[str, str], records: list[RecordedMetric]) -> None:
        self._attributes = attributes
        self._records = records

    def with_additional_attributes(self, attributes: dict[str, str]) -> "_Meter":
        return _Meter({**self._attributes, **attributes}, self._records)

    def create_counter(self, name: str, *_args: object) -> _Instrument:
        return _Instrument(name, self._attributes, self._records)

    def create_histogram_float(self, name: str, *_args: object) -> _Instrument:
        return _Instrument(name, self._attributes, self._records)


@contextmanager
def recorded_workflow_metrics() -> Iterator[list[RecordedMetric]]:
    records: list[RecordedMetric] = []
    with patch.object(temporalio.workflow, "metric_meter", return_value=_Meter({}, records)):
        yield records


def request_to_finish_records(records: list[RecordedMetric]) -> list[RecordedMetric]:
    return [record for record in records if record.name == REQUEST_TO_FINISH_METRIC]
