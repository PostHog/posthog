import abc
import asyncio
import collections.abc
import contextvars
import dataclasses
import threading
import typing

import structlog.typing
from temporalio import activity

from posthog.temporal.common.logger import get_internal_logger


class Heartbeater:
    """Regular heartbeatting during Temporal activity execution.

    This class supports both asynchronous and synchronous activities by managing:
    * An `asyncio.Task` for asynchronous activities.
    * A `threading.Thread` for synchronous activities.

    Both will the task and the thread will heartbeat regularly every
    `heartbeat_timeout` / `factor`.

    Attributes:
        details: Set this attribute to a tuple to send as heartbeat details.
        factor: Used to determine interval between regular heartbeatting.
        heartbeat_task: A reference to regular heartbeatting task maintained
            while in the asynchronous context manager to avoid garbage collection.
        heartbeat_thread: A reference to a daemonic thread heartbeatting while
            in the synchronous context manager.
        heartbeat_thread_stop_event: A stop event used to signal to the
            heartbeatting thread on context manager exit.
        logger: Reference to a logger.
    """

    def __init__(
        self,
        details: tuple[typing.Any, ...] = (),
        factor: int = 12,
        logger: structlog.typing.FilteringBoundLogger | None = None,
    ):
        self._details: tuple[typing.Any, ...] = details
        self.factor = factor

        self.heartbeat_task: asyncio.Task[None] | None = None
        self.heartbeat_on_shutdown_task: asyncio.Task[None] | None = None

        self.heartbeat_thread: threading.Thread | None = None
        self.heartbeat_thread_stop_event: threading.Event | None = None

        self.logger = logger or get_internal_logger()

    @property
    def details(self) -> tuple[typing.Any, ...]:
        """Return details if available, otherwise an empty tuple."""
        return self._details

    @details.setter
    def details(self, details: tuple[typing.Any, ...]) -> None:
        """Set tuple to be passed as heartbeat details."""
        self._details = details

    def set_from_heartbeat_details(self, details: "HeartbeatDetails") -> None:
        """Set `HeartbeatDetails` to be passed as heartbeat details."""
        self._details = tuple(details.serialize_details())

    def __enter__(self):
        """Enter managed heartbeatting context."""

        def heartbeat_forever(stop_event: threading.Event, delay: float):
            """Heartbeat forever every delay seconds or until `stop_event` is set."""
            while not stop_event.wait(delay):
                try:
                    activity.heartbeat(*self.details)
                except Exception:
                    self.logger.exception("Heartbeat failed")

        heartbeat_timeout = activity.info().heartbeat_timeout

        if not heartbeat_timeout:
            return

        context = contextvars.copy_context()
        self.heartbeat_thread_stop_event = threading.Event()

        self.heartbeat_thread = threading.Thread(
            target=context.run,
            args=(heartbeat_forever, self.heartbeat_thread_stop_event, heartbeat_timeout.total_seconds() / self.factor),
            daemon=True,
        )
        self.heartbeat_thread.start()

        return self

    async def __aenter__(self):
        """Enter managed heartbeatting context."""

        async def heartbeat_forever(delay: float) -> None:
            """Heartbeat forever every delay seconds."""
            while True:
                await asyncio.sleep(delay)
                activity.heartbeat(*self.details)

        heartbeat_timeout = activity.info().heartbeat_timeout

        if not heartbeat_timeout:
            return

        self.heartbeat_task = asyncio.create_task(heartbeat_forever(heartbeat_timeout.total_seconds() / self.factor))

        return self

    def __exit__(self, *args, **kwargs):
        """Stop heartbeatting thread on exit."""

        if self.heartbeat_thread_stop_event is not None:
            self.heartbeat_thread_stop_event.set()

        if self.heartbeat_thread is not None:
            self.heartbeat_thread.join()

        activity.heartbeat(*self.details)

        self.heartbeat_thread = None
        self.heartbeat_thread_stop_event = None

    async def __aexit__(self, *args, **kwargs):
        """Cancel heartbeatting task on exit."""
        if self.heartbeat_task is not None:
            running = self.heartbeat_task.cancel()

            if running:
                _ = await asyncio.wait([self.heartbeat_task])

        activity.heartbeat(*self.details)

        self.heartbeat_task = None


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
    """Details included in every heartbeat.

    If an activity requires tracking progress, this should be subclassed to include
    the attributes that are required for said activity. The main methods to implement
    when subclassing are `deserialize_details` and `serialize_details`. Both should
    deserialize from and serialize to a generic sequence or tuple, respectively.

    Attributes:
        _remaining: Any remaining values in the heartbeat_details tuple that we do
            not parse.
    """

    _remaining: collections.abc.Sequence[typing.Any]

    @property
    def total_details(self) -> int:
        """The total number of details that we have parsed + those remaining to parse."""
        return (len(dataclasses.fields(self.__class__)) - 1) + len(self._remaining)

    @classmethod
    @abc.abstractmethod
    def deserialize_details(cls, details: collections.abc.Sequence[typing.Any]) -> dict[str, typing.Any]:
        """Deserialize `HeartbeatDetails` from a generic sequence of details.

        This base class implementation just returns all details as `_remaining`.
        Subclasses first call this method, and then peek into `_remaining` and
        extract the details they need. For now, subclasses can only rely on the
        order in which details are serialized but in the future we may need a
        more robust way of identifying details.

        Arguments:
            details: A collection of details as returned by
                `temporalio.activity.info().heartbeat_details`
        """
        return {"_remaining": details}

    @abc.abstractmethod
    def serialize_details(self) -> tuple[typing.Any, ...]:
        """Serialize `HeartbeatDetails` to a tuple.

        Since subclasses rely on the order details are serialized, subclasses
        should be careful here to maintain a consistent serialization order. For
        example, `_remaining` should always be placed last.

        Returns:
            A tuple of serialized details.
        """
        return (self._remaining,)

    @classmethod
    def from_activity(cls, activity):
        """Instantiate this class from a Temporal Activity."""
        details = activity.info().heartbeat_details
        return cls.from_activity_details(details)

    @classmethod
    def from_activity_details(cls, details):
        parsed = cls.deserialize_details(details)
        return cls(**parsed)


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
