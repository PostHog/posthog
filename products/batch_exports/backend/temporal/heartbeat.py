import collections.abc
import dataclasses
import datetime as dt
import typing

import structlog

from posthog.temporal.common.heartbeat import (
    EmptyHeartbeatError,
    HeartbeatDetails,
    HeartbeatParseError,
    NotEnoughHeartbeatValuesError,
)

DateRange = tuple[dt.datetime, dt.datetime]

logger = structlog.get_logger()


@dataclasses.dataclass
class BatchExportRangeHeartbeatDetails(HeartbeatDetails):
    """Details included in every batch export heartbeat.

    Attributes:
        done_ranges: Date ranges that have been successfully exported.
        _remaining: Anything else in the activity details.
    """

    done_ranges: list[DateRange] = dataclasses.field(default_factory=list)
    records_completed: int = 0
    _remaining: collections.abc.Sequence[typing.Any] = dataclasses.field(default_factory=tuple)

    @classmethod
    def deserialize_details(cls, details: collections.abc.Sequence[typing.Any]) -> dict[str, typing.Any]:
        """Deserialize this from Temporal activity details.

        We expect done ranges to be available in the first index of remaining
        values. Moreover, we expect datetime values to be ISO-formatted strings.
        """
        done_ranges: list[DateRange] = []
        records_completed = 0
        remaining = super().deserialize_details(details)

        if len(remaining["_remaining"]) == 0:
            return {"done_ranges": done_ranges, "records_completed": records_completed, **remaining}

        first_detail = remaining["_remaining"][0]
        remaining["_remaining"] = remaining["_remaining"][1:]

        for date_str_tuple in first_detail:
            try:
                range_start, range_end = date_str_tuple
                datetime_bounds = (
                    dt.datetime.fromisoformat(range_start),
                    dt.datetime.fromisoformat(range_end),
                )
            except (TypeError, ValueError) as e:
                raise HeartbeatParseError("done_ranges") from e

            done_ranges.append(datetime_bounds)

        if len(remaining["_remaining"]) == 0:
            return {"done_ranges": done_ranges, "records_completed": records_completed, **remaining}

        next_detail = remaining["_remaining"][0]
        remaining["_remaining"] = remaining["_remaining"][1:]

        try:
            records_completed = int(next_detail)
        except (TypeError, ValueError) as e:
            raise HeartbeatParseError("records_completed") from e

        return {"done_ranges": done_ranges, "records_completed": records_completed, **remaining}

    def serialize_details(self) -> tuple[typing.Any, ...]:
        """Serialize this into a tuple.

        Each datetime from `self.done_ranges` must be cast to string as values must
        be JSON-serializable.
        """
        serialized_done_ranges = [
            (start.isoformat() if start is not None else start, end.isoformat()) for (start, end) in self.done_ranges
        ]
        serialized_parent_details = super().serialize_details()
        return (*serialized_parent_details[:-1], serialized_done_ranges, self.records_completed, self._remaining)

    @property
    def empty(self) -> bool:
        return len(self.done_ranges) == 0

    def track_done_range(
        self, done_range: DateRange, data_interval_start_input: str | dt.datetime | None, merge: bool = True
    ):
        """Track a range of datetime values that has been exported successfully.

        If this is the first `done_range` then we override the beginning of the
        range to ensure it covers the range from `data_interval_start_input`.

        Arguments:
            done_range: A date range of values that have been exported.
            data_interval_start_input: The `data_interval_start` input passed to
                the batch export
            merge: Whether to merge the new range with existing ones.
        """
        if self.empty is True:
            if data_interval_start_input is None:
                data_interval_start = dt.datetime.fromtimestamp(0, tz=dt.UTC)
            elif isinstance(data_interval_start_input, str):
                data_interval_start = dt.datetime.fromisoformat(data_interval_start_input)
            else:
                data_interval_start = data_interval_start_input

            done_range = (data_interval_start, done_range[1])

        self.insert_done_range(done_range, merge=merge)

    def insert_done_range(self, done_range: DateRange, merge: bool = True):
        """Insert a date range into `self.done_ranges` in order."""
        for index, range in enumerate(self.done_ranges, start=0):
            if done_range[0] > range[1]:
                continue

            # We have found the index where this date range should go in.
            if done_range[0] == range[1]:
                self.done_ranges.insert(index + 1, done_range)
            else:
                self.done_ranges.insert(index, done_range)
            break
        else:
            # Date range should go at the end
            self.done_ranges.append(done_range)

        if merge:
            self.merge_done_ranges()

    def merge_done_ranges(self):
        """Merge as many date ranges together as possible in `self.done_ranges`.

        This method looks for ranges whose opposite ends are touching and merges
        them together. Notice that this method does not have enough information
        to merge ranges that are not touching.
        """
        marked_for_deletion = set()
        for index, range in enumerate(self.done_ranges, start=0):
            if index in marked_for_deletion:
                continue
            try:
                next_range = self.done_ranges[index + 1]
            except IndexError:
                continue

            if next_range[0] == range[1]:
                # Touching start of next range with end of range.
                # End of next range set as end of existing range.
                # Next range marked for deletion as it's now covered by range.
                self.done_ranges[index] = (range[0], next_range[1])
                marked_for_deletion.add(index + 1)

        for index in marked_for_deletion:
            self.done_ranges.pop(index)

    def complete_done_ranges(self, data_interval_end_input: str | dt.datetime):
        """Complete the entire range covered by the batch export.

        This is meant to be called at the end of a batch export to ensure
        `self.done_ranges` covers the entire batch period from whichever was the
        first range tracked until `data_interval_end_input`.

        All ranges will be essentially merged into one (well, replaced by one)
        covering everything, so it is very important to only call this once
        everything is done.
        """
        if isinstance(data_interval_end_input, str):
            data_interval_end = dt.datetime.fromisoformat(data_interval_end_input)
        else:
            data_interval_end = data_interval_end_input

        self.done_ranges = [(self.done_ranges[0][0], data_interval_end)]


HeartbeatType = typing.TypeVar("HeartbeatType", bound=HeartbeatDetails)


async def should_resume_from_activity_heartbeat(
    activity, heartbeat_type: type[HeartbeatType]
) -> tuple[bool, HeartbeatType | None]:
    """Check if a batch export should resume from an activity's heartbeat details.

    We understand that a batch export should resume any time that we receive heartbeat details and
    those details can be correctly parsed. However, the decision is ultimately up  to the batch export
    activity to decide if it must resume and how to do so.

    Returns:
        A tuple with the first element indicating if the batch export should resume. If the first element
        is True, the second tuple element will be the heartbeat details themselves, otherwise None.
    """
    try:
        heartbeat_details = heartbeat_type.from_activity(activity)

    except EmptyHeartbeatError:
        # We don't log this as it's the expected exception when heartbeat is empty.
        heartbeat_details = None
        received = False

    except NotEnoughHeartbeatValuesError:
        heartbeat_details = None
        received = False
        await logger.awarning("Details from previous activity execution did not contain the expected amount of values")

    except HeartbeatParseError:
        heartbeat_details = None
        received = False
        await logger.awarning("Details from previous activity execution could not be parsed.")

    except Exception:
        # We should start from the beginning, but we make a point to log unexpected errors.
        # Ideally, any new exceptions should be added to the previous blocks after the first time and we will never land here.
        heartbeat_details = None
        received = False
        await logger.aexception("Did not receive details from previous activity Execution due to an unexpected error")

    else:
        received = True
        await logger.adebug(
            f"Received details from previous activity: {heartbeat_details}",
        )

    return received, heartbeat_details
