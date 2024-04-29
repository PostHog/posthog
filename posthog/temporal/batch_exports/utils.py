import asyncio
import collections.abc
import typing
import uuid
from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import update_batch_export_run

T = typing.TypeVar("T")


def peek_first_and_rewind(
    gen: collections.abc.Generator[T, None, None],
) -> tuple[T, collections.abc.Generator[T, None, None]]:
    """Peek into the first element in a generator and rewind the advance.

    The generator is advanced and cannot be reversed, so we create a new one that first
    yields the element we popped before yielding the rest of the generator.

    Returns:
        A tuple with the first element of the generator and the generator itself.
    """
    first = next(gen)

    def rewind_gen() -> collections.abc.Generator[T, None, None]:
        """Yield the item we popped to rewind the generator."""
        yield first
        yield from gen

    return (first, rewind_gen())


async def try_set_batch_export_run_to_running(run_id: str | None, logger, timeout: float = 10.0) -> None:
    """Try to set a batch export run to 'RUNNING' status, but do nothing if we fail or if 'run_id' is 'None'.

    This is intended to be used within a batch export's 'insert_*' activity. These activities cannot afford
    to fail if our database is experiencing issues, as we should strive to not let issues in our infrastructure
    propagate to users. So, we do a best effort update and swallow the exception if we fail.

    Even if we fail to update the status here, the 'finish_batch_export_run' activity at the end of each batch
    export will retry indefinitely and wait for postgres to recover, eventually making a final update with
    the status. This means that, worse case, the batch export status won't be displayed as 'RUNNING' while running.
    """
    if run_id is None:
        return

    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                update_batch_export_run,
                uuid.UUID(run_id),
                status=BatchExportRun.Status.RUNNING,
            ),
            timeout=timeout,
        )
    except Exception as e:
        logger.warn(
            "Unexpected error trying to set batch export to 'RUNNING' status. Run will continue but displayed status may not be accurate until run finishes",
            exc_info=e,
        )
