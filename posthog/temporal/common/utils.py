import abc
import collections.abc
import dataclasses
import datetime as dt
import typing


class EmptyHeartbeatError(Exception):
    """Raised when an activity heartbeat is empty.

    This is also the error we expect when no heartbeatting is happening, as the sequence will be empty.
    """

    def __init__(self):
        super().__init__(f"Heartbeat details sequence is empty")


class NotEnoughHeartbeatValuesError(Exception):
    """Raised when an activity heartbeat doesn't contain the right amount of values we expect."""

    def __init__(self, details_len: int, expected: int):
        super().__init__(f"Not enough values in heartbeat details (expected {expected}, got {details_len})")


class HeartbeatParseError(Exception):
    """Raised when an activity heartbeat cannot be parsed into it's expected types."""

    def __init__(self, field: str):
        super().__init__(f"Parsing {field} from heartbeat details encountered an error")


@dataclasses.dataclass
class HeartbeatDetails(metaclass=abc.ABCMeta):
    """The batch export details included in every heartbeat.

    Each batch export destination should subclass this and implement whatever details are specific to that
    batch export and required to resume it.

    Attributes:
        last_inserted_at: The last inserted_at we managed to upload or insert, depending on the destination.
        _remaining: Any remaining values in the heartbeat_details tuple that we do not parse.
    """

    _remaining: collections.abc.Sequence[typing.Any]

    @property
    def total_details(self) -> int:
        """The total number of details that we have parsed + those remaining to parse."""
        return (len(dataclasses.fields(self.__class__)) - 1) + len(self._remaining)

    @classmethod
    @abc.abstractmethod
    def deserialize_details(cls, details: collections.abc.Sequence[typing.Any]) -> dict[str, typing.Any]:
        return {"_remaining": details}

    @abc.abstractmethod
    def serialize_details(self) -> tuple[typing.Any, ...]:
        return (self._remaining,)

    @classmethod
    def from_activity(cls, activity):
        details = activity.info().heartbeat_details
        return cls.from_activity_details(details)

    @classmethod
    def from_activity_details(cls, details):
        parsed = cls.deserialize_details(details)
        return cls(**parsed)


DateRange = tuple[dt.datetime, dt.datetime]


@dataclasses.dataclass
class BatchExportRangeHeartbeatDetails(HeartbeatDetails):
    _remaining: collections.abc.Sequence[typing.Any] = dataclasses.field(default_factory=tuple)
    done_ranges: list[DateRange] = dataclasses.field(default_factory=list)

    @classmethod
    def deserialize_details(cls, details: collections.abc.Sequence[typing.Any]) -> dict[str, typing.Any]:
        """Attempt to initialize HeartbeatDetails from an activity's details."""
        done_ranges = []
        remaining = super().deserialize_details(details)

        if len(remaining["_remaining"]) == 0:
            return {"done_ranges": done_ranges, **remaining}

        first_detail = remaining["_remaining"][0]
        remaining["_remaining"] = remaining["_remaining"][1:]

        for date_str_tuple in first_detail:
            range_start, range_end = date_str_tuple

            try:
                datetime_bounds = (
                    dt.datetime.fromisoformat(range_start),
                    dt.datetime.fromisoformat(range_end),
                )
            except (TypeError, ValueError) as e:
                raise HeartbeatParseError("ranges") from e

            done_ranges.append(datetime_bounds)

        return {"done_ranges": done_ranges, **remaining}

    def serialize_details(self) -> tuple[typing.Any, ...]:
        """Attempt to initialize HeartbeatDetails from an activity's details."""
        return (
            [(start.isoformat() if start is not None else start, end.isoformat()) for (start, end) in self.done_ranges],
            *super().serialize_details(),
        )

    def insert_done_range(self, done_range: DateRange, merge: bool = True):
        for index, range in enumerate(self.done_ranges, start=0):
            if done_range[0] > range[1]:
                continue
            # We have found the index where this date range should go in.
            self.done_ranges.insert(index, range)
            break
        else:
            # Date range should go at the end
            self.done_ranges.append(done_range)

        if merge:
            self.merge_done_ranges()

    def merge_done_ranges(self):
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


@dataclasses.dataclass
class BatchExportHeartbeatDetails(HeartbeatDetails):
    last_inserted_at: dt.datetime

    @classmethod
    def deserialize_details(cls, details: collections.abc.Sequence[typing.Any]) -> dict[str, typing.Any]:
        """Attempt to initialize HeartbeatDetails from an activity's info."""
        if len(details) == 0:
            raise EmptyHeartbeatError()

        parsed = super().deserialize_details(details)

        try:
            last_inserted_at = dt.datetime.fromisoformat(details[0])
        except (TypeError, ValueError) as e:
            raise HeartbeatParseError("last_inserted_at") from e

        return {**parsed, "last_inserted_at": last_inserted_at}


@dataclasses.dataclass
class DataImportHeartbeatDetails(HeartbeatDetails):
    """Data import heartbeat details.

    Attributes:
        endpoint: The endpoint we are importing data from.
        cursor: The cursor we are using to paginate through the endpoint.
    """

    endpoint: str
    cursor: str

    @classmethod
    def from_activity(cls, activity):
        """Attempt to initialize DataImportHeartbeatDetails from an activity's info."""
        details = activity.info().heartbeat_details

        if len(details) == 0:
            raise EmptyHeartbeatError()

        if len(details) != 2:
            raise NotEnoughHeartbeatValuesError(len(details), 2)

        return cls(endpoint=details[0], cursor=details[1], _remaining=details[2:])


HeartbeatType = typing.TypeVar("HeartbeatType", bound=HeartbeatDetails)


async def should_resume_from_activity_heartbeat(
    activity, heartbeat_type: type[HeartbeatType], logger
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


BatchExportRangeHeartbeatDetailsType = typing.TypeVar(
    "BatchExportRangeHeartbeatDetailsType", bound=BatchExportRangeHeartbeatDetails
)


async def should_resume_from_activity_heartbeat_ranges(
    activity, heartbeat_type: type[BatchExportRangeHeartbeatDetailsType], logger
) -> tuple[bool, BatchExportRangeHeartbeatDetailsType | None]:
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
