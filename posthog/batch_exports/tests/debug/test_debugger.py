import datetime as dt
import itertools
import operator

import pyarrow as pa
import pytest

from posthog.batch_exports.debug.debugger import BatchExportsDebugger, ColumnDebugStatistics
from posthog.batch_exports.models import BatchExport, BatchExportDestination, BatchExportRun

pytestmark = [
    pytest.mark.django_db,
]


def test_debugger_loads_batch_exports_for_team(team):
    batch_exports = []
    destination = BatchExportDestination(
        type=BatchExportDestination.Destination.S3,
        config={
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "use_virtual_style_addressing": True,
        },
    )
    for i in range(5):
        batch_exports.append(
            BatchExport(team_id=team.pk, name=f"test-batch-export-{i}", interval="hour", destination=destination)
        )
    destination.save()
    for batch_export in batch_exports:
        batch_export.save()

    bedbg = BatchExportsDebugger(team.pk)

    assert len(bedbg.loaded_batch_exports) == 5
    assert all(batch_export in bedbg.loaded_batch_exports for batch_export in batch_exports)


def test_debugger_loads_empty_batch_export_for_team(team):
    bedbg = BatchExportsDebugger(team.pk)

    assert len(bedbg.loaded_batch_exports) == 0


def test_debugger_sets_working_batch_export_with_name(team):
    batch_exports = {}
    destination = BatchExportDestination(
        type=BatchExportDestination.Destination.S3,
        config={
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "use_virtual_style_addressing": True,
        },
    )
    for i in range(5):
        batch_exports[f"test-batch-export-{i}"] = BatchExport(
            team_id=team.pk, name=f"test-batch-export-{i}", interval="hour", destination=destination
        )

    destination.save()
    for _, batch_export in batch_exports.items():
        batch_export.save()

    bedbg = BatchExportsDebugger(team.pk)

    for i in range(5):
        name = f"test-batch-export-{i}"
        bedbg.set_batch_export_from_loaded(name)
        assert bedbg.batch_export == batch_exports[name]


def test_debugger_sets_working_batch_export_with_uuid(team):
    batch_exports = {}
    destination = BatchExportDestination(
        type=BatchExportDestination.Destination.S3,
        config={
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "use_virtual_style_addressing": True,
        },
    )
    destination.save()

    for i in range(5):
        batch_export = BatchExport(
            team_id=team.pk, name=f"test-batch-export-{i}", interval="hour", destination=destination
        )
        batch_exports[batch_export.id] = batch_export
        batch_export.save()

    bedbg = BatchExportsDebugger(team.pk)

    for batch_export_id, batch_export in batch_exports.items():
        bedbg.set_batch_export_from_loaded(batch_export_id)
        assert bedbg.batch_export == batch_export


def test_debugger_can_load_different_sets_of_batch_exports(team):
    batch_exports = []

    destination_s3 = BatchExportDestination(
        type=BatchExportDestination.Destination.S3,
        config={},
    )
    destination_bigquery = BatchExportDestination(
        type=BatchExportDestination.Destination.BIGQUERY,
        config={},
    )
    destination_s3.save()
    destination_bigquery.save()

    for destination, deleted, paused in itertools.product(
        (destination_s3, destination_bigquery), (True, False), (True, False)
    ):
        batch_export = BatchExport(
            team_id=team.pk,
            name=f"test-batch-export-{str(destination.type)}-{str(deleted)}-{str(paused)}",
            interval="hour",
            destination=destination,
            paused=paused,
            deleted=deleted,
        )
        batch_export.save()
        batch_exports.append(batch_export)

    bedbg = BatchExportsDebugger(team.pk)

    loaded = bedbg.load_batch_exports(deleted=True)

    assert len(loaded) == 4
    assert bedbg.loaded_batch_exports == loaded
    assert all(batch_export.deleted is True for batch_export in loaded)

    loaded = bedbg.load_batch_exports(paused=True, deleted=None)

    assert len(loaded) == 4
    assert bedbg.loaded_batch_exports == loaded
    assert all(batch_export.paused is True for batch_export in loaded)

    loaded = bedbg.load_batch_exports(destination="S3", deleted=None)

    assert len(loaded) == 4
    assert bedbg.loaded_batch_exports == loaded
    assert all(batch_export.destination.type == BatchExportDestination.Destination.S3 for batch_export in loaded)

    loaded = bedbg.load_batch_exports(destination="bigquery", deleted=None)

    assert len(loaded) == 4
    assert bedbg.loaded_batch_exports == loaded
    assert all(batch_export.destination.type == BatchExportDestination.Destination.BIGQUERY for batch_export in loaded)

    loaded = bedbg.load_batch_exports(name="test-batch-export-S3-False-False")

    assert len(loaded) == 1
    assert bedbg.loaded_batch_exports == loaded
    assert all(batch_export.name == "test-batch-export-S3-False-False" for batch_export in loaded)


def test_debugger_get_latest_run(team):
    destination = BatchExportDestination(
        type=BatchExportDestination.Destination.S3,
        config={
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "use_virtual_style_addressing": True,
        },
    )
    destination.save()
    batch_export = BatchExport(team_id=team.pk, name=f"test-batch-export", interval="hour", destination=destination)
    batch_export.save()

    runs = []

    for i in range(5):
        end = dt.datetime(2025, 6, 1, 0, 0, 0) - dt.timedelta(hours=i)
        start = end - dt.timedelta(hours=1)

        run = BatchExportRun(
            status=BatchExportRun.Status.COMPLETED,
            batch_export=batch_export,
            data_interval_start=start,
            data_interval_end=end,
            last_updated_at=end,
            created_at=start,
            finished_at=end,
        )
        run.save()
        runs.append(run)

    for i in range(5):
        end = dt.datetime(2025, 5, 1, 0, 0, 0) - dt.timedelta(hours=i)
        start = end - dt.timedelta(hours=1)

        run = BatchExportRun(
            status=BatchExportRun.Status.FAILED,
            batch_export=batch_export,
            data_interval_start=start,
            data_interval_end=end,
            last_updated_at=end,
            created_at=start,
            finished_at=end,
        )
        run.save()
        runs.append(run)

    bedbg = BatchExportsDebugger(team.pk)
    get_created_at = operator.attrgetter("created_at")
    get_latest_updated_at = operator.attrgetter("last_updated_at")
    runs.sort(key=get_latest_updated_at, reverse=True)

    latest = bedbg.get_latest_run()
    assert latest == runs[0]

    latest = bedbg.get_latest_run(offset=1)
    assert latest == runs[1]

    get_created_at = operator.attrgetter("created_at")
    runs.sort(key=get_created_at, reverse=True)

    latest = bedbg.get_latest_run(order_by="created_at")
    assert latest == runs[0]

    failed_runs = [run for run in runs if run.status == BatchExportRun.Status.FAILED]
    failed_runs.sort(key=get_latest_updated_at, reverse=True)

    latest = bedbg.get_latest_run(status="failed")
    assert latest == failed_runs[0]

    failed_runs.sort(key=get_created_at, reverse=True)

    latest = bedbg.get_latest_run(status="failed", order_by="created_at")
    assert latest == failed_runs[0]


def test_column_debug_statistics():
    n_legs = pa.array([2, 2, 4, 4, 5, 100])
    animals = pa.array(["Flamingo", "Parrot", "Dog", "Horse", "Brittle stars", "Centipede"])
    names = ["n_legs", "animals"]

    record_batch = pa.RecordBatch.from_arrays([n_legs, animals], names=names)  # type: ignore
    stats = ColumnDebugStatistics.from_record_batch(record_batch, column_name="n_legs")

    assert stats.count == 6
    assert stats.unique_values == {2, 4, 5, 100}
    assert stats.size_bytes == n_legs.nbytes
    assert stats.name == "n_legs"

    stats += record_batch

    assert stats.count == 12
    assert stats.unique_values == {2, 4, 5, 100}
    assert stats.size_bytes == n_legs.nbytes * 2
    assert stats.name == "n_legs"
