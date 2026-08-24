"""Working out which time ranges a batch export run needs to query, and from where.

A run covers a data interval, but it may resume after a crash with part of that interval
already exported, and which ClickHouse table to read depends on how recent the interval is.
"""

import typing
import asyncio
import datetime as dt
import operator
import collections.abc

from django.conf import settings

from products.batch_exports.backend.service import BackfillDetails


def is_5_min_batch_export(full_range: tuple[dt.datetime | None, dt.datetime]) -> bool:
    start_at, end_at = full_range
    if start_at:
        return (end_at - start_at) == dt.timedelta(seconds=300)
    return False


def use_distributed_events_recent_table(
    is_backfill: bool, backfill_details: BackfillDetails | None, data_interval_start: dt.datetime | None
) -> bool:
    """We should use the distributed_events_recent table if it's not a backfill (backfill_details is None) or the
    backfill is within the last 6 days.

    We also check the data_interval_start to make sure it's also within the last 6 days (should always be the case for
    realtime batch exports but for tests it may not be the case)

    The events_recent table, and by extension, the distributed_events_recent table, only have event data from the last 7
    days (we use 6 days to give some buffer).
    """

    if (
        not is_backfill
        and data_interval_start
        and data_interval_start > (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=6))
    ):
        return True

    backfill_start_at = None
    if backfill_details and backfill_details.start_at:
        backfill_start_at = dt.datetime.fromisoformat(backfill_details.start_at)
    if backfill_start_at and backfill_start_at > (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=6)):
        return True

    return False


def generate_query_ranges(
    remaining_range: tuple[dt.datetime | None, dt.datetime],
    done_ranges: collections.abc.Sequence[tuple[dt.datetime, dt.datetime]],
) -> typing.Iterator[tuple[dt.datetime | None, dt.datetime]]:
    """Recursively yield ranges of dates that need to be queried.

    There are essentially 3 scenarios we are expecting:
    1. The batch export just started, so we expect `done_ranges` to be an empty
       list, and thus should return the `remaining_range`.
    2. The batch export crashed mid-execution, so we have some `done_ranges` that
       do not completely add up to the full range. In this case we need to yield
       ranges in between all the done ones.
    3. The batch export crashed right after we finish, so we have a full list of
       `done_ranges` adding up to the `remaining_range`. In this case we should not
       yield anything.

    Case 1 is fairly trivial and we can simply return `remaining_range` if we get
    an empty `done_ranges`.

    Case 2 is more complicated and we can expect that the ranges produced by this
    function will lead to duplicate events selected, as our batch export query is
    inclusive in the lower bound. Since multiple rows may have the same
    `inserted_at` we cannot simply skip an `inserted_at` value, as there may be a
    row that hasn't been exported as it with the same `inserted_at` as a row that
    has been exported. So this function will return ranges with `inserted_at`
    values that were already exported for at least one event. Ideally, this is
    *only* one event, but we can never be certain.
    """
    if len(done_ranges) == 0:
        yield remaining_range
        return

    epoch = dt.datetime.fromtimestamp(0, tz=dt.UTC)
    list_done_ranges: list[tuple[dt.datetime, dt.datetime]] = list(done_ranges)

    list_done_ranges.sort(key=operator.itemgetter(0))

    while True:
        try:
            next_range: tuple[dt.datetime | None, dt.datetime] = list_done_ranges.pop(0)
        except IndexError:
            if remaining_range[0] != remaining_range[1]:
                # If they were equal it would mean we have finished.
                yield remaining_range

            return
        else:
            candidate_end_at = next_range[0] if next_range[0] is not None else epoch

        candidate_start_at = remaining_range[0]
        remaining_range = (next_range[1], remaining_range[1])

        if candidate_start_at is not None and candidate_start_at >= candidate_end_at:
            # We have landed within a done range.
            continue

        if candidate_start_at is None and candidate_end_at == epoch:
            # We have landed within the first done range of a backfill.
            continue

        yield (candidate_start_at, candidate_end_at)


async def wait_for_delta_past_data_interval_end(
    data_interval_end: dt.datetime, delta: dt.timedelta = dt.timedelta(seconds=30)
) -> None:
    """Wait for some time after `data_interval_end` before querying ClickHouse."""
    if settings.TEST:
        return

    target = data_interval_end.astimezone(dt.UTC)
    now = dt.datetime.now(dt.UTC)

    while target + delta > now:
        now = dt.datetime.now(dt.UTC)
        remaining = (target + delta) - now
        # Sleep between 1-10 seconds, there shouldn't ever be the need to wait too long.
        await asyncio.sleep(min(max(remaining.total_seconds(), 1), 10))
