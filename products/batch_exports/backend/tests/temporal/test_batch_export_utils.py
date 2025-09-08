import asyncio
import datetime as dt

import pytest

import pyarrow as pa

from posthog.batch_exports.models import BatchExportRun
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

from products.batch_exports.backend.temporal.utils import (
    JsonType,
    make_retryable_with_exponential_backoff,
    set_status_to_running_task,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest.fixture
async def s3_batch_export(
    ateam,
    temporal_client,
):
    """Provide a batch export for tests, not intended to be used."""
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "a-bucket",
            "region": "us-east-1",
            "prefix": "a-key",
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],  # type: ignore
        destination_data=batch_export_data["destination"],  # type: ignore
        interval=batch_export_data["interval"],  # type: ignore
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


async def test_batch_export_run_is_set_to_running(ateam, s3_batch_export):
    """Test background task sets batch export to running."""
    some_date = dt.datetime(2021, 12, 5, 13, 23, 0, tzinfo=dt.UTC)

    run = await BatchExportRun.objects.acreate(
        batch_export_id=s3_batch_export.id,
        data_interval_end=some_date,
        data_interval_start=some_date - dt.timedelta(hours=1),
        status=BatchExportRun.Status.STARTING,
    )

    async with set_status_to_running_task(run_id=str(run.id)) as task:
        assert task is not None

        await asyncio.wait([task])

        assert task.done()
        assert task.exception() is None

    await run.arefresh_from_db()
    assert run.status == BatchExportRun.Status.RUNNING


async def test_make_retryable_with_exponential_backoff_called_max_attempts():
    """Test function wrapped is called all `max_attempts` times."""
    counter = 0

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(raise_value_error, max_retry_delay=1)()

    assert counter == 5


async def test_make_retryable_with_exponential_backoff_called_max_attempts_if_timesout():
    """Test function wrapped is called all `max_attempts` times on a timeout."""
    counter = 0

    async def raise_value_error():
        nonlocal counter
        counter += 1
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        await make_retryable_with_exponential_backoff(raise_value_error, max_retry_delay=1, timeout=1)()

    assert counter == 5


async def test_make_retryable_with_exponential_backoff_called_max_attempts_if_func_returns_retryable():
    """Test function wrapped is called all `max_attempts` times if `is_exception_retryable` returns `True`."""
    counter = 0

    def is_exception_retryable(err):
        return True

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(
            raise_value_error, is_exception_retryable=is_exception_retryable, max_retry_delay=1
        )()

    assert counter == 5


async def test_make_retryable_with_exponential_backoff_raises_if_func_returns_not_retryable():
    """Test function wrapped raises immediately if `is_exception_retryable` returns `False`."""
    counter = 0

    def is_exception_retryable(err):
        return False

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(
            raise_value_error, is_exception_retryable=is_exception_retryable
        )()

    assert counter == 1


async def test_make_retryable_with_exponential_backoff_raises_if_not_retryable():
    """Test function wrapped raises immediately if exception not in `retryable_exceptions`."""
    counter = 0

    async def raise_value_error():
        nonlocal counter
        counter += 1

        raise ValueError("I failed")

    with pytest.raises(ValueError):
        await make_retryable_with_exponential_backoff(raise_value_error, retryable_exceptions=(TypeError,))()

    assert counter == 1


@pytest.mark.parametrize(
    "input,expected",
    [
        ([b'{"asdf": "\udee5\ud83e\udee5\\ud83e"}'], [{"asdf": "????"}]),
        ([b'{"asdf": "\\"Hello\\" \\udfa2"}'], [{"asdf": '"Hello" ?'}]),
        ([b'{"asdf": "\n"}'], [{"asdf": "\n"}]),
        ([b'{"asdf": "\\n"}'], [{"asdf": "\n"}]),
        (
            [b'{"finally": "a", "normal": "json", "thing": 1, "bool": false}'],
            [{"finally": "a", "normal": "json", "thing": 1, "bool": False}],
        ),
    ],
)
def test_json_type_as_py(input, expected):
    array = pa.array(input)
    casted_array = array.cast(JsonType())
    result = casted_array.to_pylist()

    assert result == expected
