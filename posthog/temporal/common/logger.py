"""Module configuring structlog for Temporal logging.

This module defines how to configure structlog for Temporal logging. This effectively
replaces the Temporal logging utilities, and users of Temporal are strongly encouraged
to prefer structlog.

In order to configure structlog, the `configure_logger` function defined in this module
must be called at the start of each worker process, as it is done in
`posthog.management.commands.start_temporal_worker`.

Developers of Temporal workflows should consider the two logging modes offered by this
module:
* Write: Logs are written to stdout.
* Produce: Logs are produced to Kafka/ClickHouse and ingested into `log_entries`.

By default, the logger returned by `structlog.get_logger` or this module's `get_logger`
will execute both modes, meaning logs issued will be written to stdout and produced to
ClickHouse if requirements are met.

Loggers (of both modes) can be used in both activity and workflow context. Developers
are encouraged to call `get_logger` once at the top of their modules, and then `bind()`
their loggers when starting an activity or workflow, including any relevant context.
Temporal context, like activity ID, workflow type, attempt number, and others, will be
automatically included.
"""

import ssl
import sys
import json
import typing
import asyncio
import functools
import contextvars
import collections.abc

from django.conf import settings

import aiokafka
import structlog
import temporalio.activity
import temporalio.workflow
from structlog._frames import _find_first_app_frame_and_name
from structlog._log_levels import LEVEL_TO_NAME, NAME_TO_LEVEL
from structlog.processors import EventRenamer

from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES

BACKGROUND_LOGGER_TASKS: dict[str, asyncio.Task[typing.Any]] = {}

LogQueue = asyncio.Queue[bytes]


def get_produce_only_logger(name: str | None = None):
    """Return a logger configured to only produce logs to Kafka/ClickHouse."""
    return structlog.get_logger(name, False, True)


def get_write_only_logger(name: str | None = None):
    """Return a logger configured to only write to configured file (stdout)."""
    return structlog.get_logger(name, True, False)


def get_logger(name: str | None = None, write: bool = True, produce: bool = True):
    """Return a structlog logger.

    Optionally configure whether this logger has produce and/or write capabilities. By
    default, it has both.
    """
    return structlog.get_logger(name, write, produce)


class Logger:
    """A logger with support for producing log messages as well as writing."""

    def __init__(
        self,
        name: str,
        queue: LogQueue | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        file: typing.TextIO | None = None,
    ):
        self.write_logger = structlog.WriteLogger(file=file)
        self.name = name
        self.queue = queue
        self.loop = loop

    def __repr__(self) -> str:
        return f"<Logger(name={self.name}, file={self.write_logger._file!r}, queue={self.queue!r})>"

    def process(self, write_message: str | None, produce_message: bytes | None = None) -> None:
        """Handle messages by dispatching to write logger or production."""
        if write_message:
            self.write(write_message)

        if produce_message:
            self.produce(produce_message)

    def produce(self, message: bytes) -> None:
        """Produce message to `self.queue`."""
        if self.queue and self.loop:
            asyncio.run_coroutine_threadsafe(self.queue.put(message), self.loop)

    def write(self, message: str) -> None:
        """Write messages to file using write logger."""
        self.write_logger.msg(message)

    log = debug = info = warn = warning = process
    fatal = failure = err = error = critical = exception = process


class LogMessages(typing.TypedDict):
    """Typed dictionary returned by renderer passed to `Logger` ."""

    write_message: str | None
    produce_message: bytes | None


DEFAULT_SERIALIZER = functools.partial(json.dumps, default=str)


class LogMessagesRenderer:
    """Render messages for writing and producing.

    Both are passed along to `Logger.process`.
    """

    def __init__(
        self,
        event_key: str = "event",
        json_serializer: typing.Callable[[structlog.types.EventDict], str] = DEFAULT_SERIALIZER,
    ):
        """Initialize renderer.

        Args:
            event_key: The key where the main event message is found. Defaults to
                "event" in line with other structlog renderers.
            json_serializer: Function used to serialize as JSON. By default, uses
                stdlib's `json.dumps`.
        """
        self.json_serializer = json_serializer
        self.event_key = event_key

    def __call__(self, logger: Logger, name: str, event_dict: structlog.types.EventDict) -> LogMessages:
        """Return rendered messages meant for `Logger.process`.

        The 'write_only' and 'produce_only' context keys can be used to limit what gets
        rendered. These are set by users when logging. By default, messages for both
        writing and producing will be rendered.
        """
        write_only = event_dict.pop("write_only", False)
        produce_only = event_dict.pop("produce_only", False)

        write_message = None
        if not produce_only:
            write_message = self.json_serializer(event_dict)

        produce_message = None
        if not write_only:
            try:
                log_source, log_source_id = resolve_log_source(event_dict["workflow_type"], event_dict["workflow_id"])

                message_dict = {
                    "instance_id": event_dict["workflow_run_id"],
                    "level": event_dict["level"],
                    "log_source": log_source,
                    "log_source_id": log_source_id,
                    "message": event_dict[self.event_key],
                    "team_id": event_dict["team_id"],
                    "timestamp": event_dict["timestamp"],
                }
            except KeyError:
                # We don't have the required keys to ingest this log.
                # This could be because we are running outside an Activity/Workflow context
                # or because 'team_id' was not set.
                pass
            else:
                produce_message = self.json_serializer(message_dict).encode("utf-8")

        return {"write_message": write_message, "produce_message": produce_message}


class ProduceOnlyLogger(Logger):
    """A logger that can only be used for producing."""

    def write(self, message: str) -> None:
        return None


class WriteOnlyLogger(Logger):
    """A logger that can only be used for writing."""

    def produce(self, message: bytes) -> None:
        return None


class LoggerFactory:
    """A logger factory to configure structlog.

    This factory introduces two `bool` parameters that can be passed to
    `structlog.get_logger`. These control whether the loggers will have writing and
    producing capabilities, or one of them.
    """

    def __init__(
        self,
        queue: LogQueue | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        file: typing.TextIO | None = None,
        is_test_or_tty: bool = False,
    ):
        self.loop = loop
        self.queue = queue
        self.file = file
        self.is_test_or_tty = is_test_or_tty

    def __call__(self, name: str | None = None, write: bool = True, produce: bool = True) -> Logger:
        """Return a logger depending on configuration.

        In particular, when running in a TTY or during tests, this logger will be a
        basic `WriteOnlyLogger`. This means that:
        * Rendering will be delegated to `structlog.dev.ConsoleRenderer`.
        * We will only write to a file (stdout by default), meaning no logs will be
            produced.

        The first point is motivated by our need to see logs when developing locally in
        human readable format with pretty colors. And the second point's motivation is
        that producing logs requires additional setup (i.e. the `log_entries` table
        existing and consuming) that is not usually available.

        What this means is that we get pretty-printed logs when running Temporal workers
        locally and otherwise JSON logs for production.

        Args:
           name: A name for the logger, when not set, it resolves to first `__name__`
               after omitting all structlog internal stuff, which means it should
               resolve to the module's `__name__` where this is being called in.
           write: In production, controls whether the logger should write to file. In
               tests or local development, this is ignored.
           produce: In production, controls whether the logger should produce to queue.
               In tests or local development, this is ignored.
        """
        if name:
            resolved_name = name
        else:
            # NOTE: This means we should pass "posthog.temporal.common.logger" as the
            # name for this module's logger, if any is used.
            _, resolved_name = _find_first_app_frame_and_name(["posthog.temporal.common.logger"])

        if self.is_test_or_tty:
            return WriteOnlyLogger(resolved_name, file=self.file)

        match (produce, write):
            case (True, True):
                return Logger(resolved_name, queue=self.queue, loop=self.loop, file=self.file)
            case (True, False):
                return ProduceOnlyLogger(resolved_name, queue=self.queue, loop=self.loop)
            case (False, True):
                return WriteOnlyLogger(resolved_name, file=self.file)
            case _:
                # We could match on (False, False) as that's the only possible pattern left.
                # But dynamic typing means this could be anything.
                # Still, the error message assumes (False, False).
                raise ValueError("Logger must either produce, write, or both")


def _make_method(name):
    """Utility function used to generate logging methods."""

    def _(self, event, *args, **kwargs):
        event = _format_args(event, *args)

        if name == "exception":
            kwargs = _set_exc_info(async_method=False, **kwargs)
            method_name = "error"
        else:
            method_name = name

        return self._proxy_to_logger(method_name, event, **kwargs)

    _.__name__ = name

    return _


def _make_async_method(name):
    """Utility function used to generate async logging methods."""

    async def _(self, event, *args, **kwargs):
        event = _format_args(event, *args)

        if name == "exception" or name == "error":
            kwargs = _set_exc_info(async_method=True, **kwargs)
            method_name = "error"
        else:
            method_name = name

        scs_token = structlog.contextvars._ASYNC_CALLING_STACK.set(sys._getframe().f_back)  # type: ignore[arg-type]
        ctx = contextvars.copy_context()

        try:
            return await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: ctx.run(lambda: self._proxy_to_logger(method_name, event, **kwargs)),
            )
        finally:
            structlog.contextvars._ASYNC_CALLING_STACK.reset(scs_token)

    _.__name__ = f"a{name}"

    return _


def _format_args(event: str, *args) -> str:
    """Utility function to format args like stdlib's logging."""
    if args:
        if len(args) == 1 and isinstance(args[0], dict) and args[0]:
            args = args[0]  # type: ignore

        event %= args
    return event


def _set_exc_info(async_method: bool, **kwargs):
    """Utility function to set `exc_info` as required."""
    if async_method is True and kwargs.get("exc_info", True) is True:
        # Exception is lost when call passed to executor, so we must capture it now.
        kwargs["exc_info"] = sys.exc_info()
    else:
        kwargs.setdefault("exc_info", True)

    return kwargs


class WrapperLogger(structlog.BoundLoggerBase):
    """Wrap loggers returned by `LoggerFactory`.

    This wrapper implements all the usual logging methods and async variants based on
    structlog's `make_filtering_bound_logger`. However, this additionally treats
    positional arguments like the stdlib's `logging.Logger`.

    This means that if the first positional argument is a dictionary, we can support
    named %-style formatting.

    Examples:
        %-style named formatting:

        >>> logger = structlog.get_logger() # Returns `WrapperLogger` wrapping `Logger`
        >>> logger.info("Hello %(name)s", {"name": "World"})
        {"event": "Hello World"}

        %-style formatting:

        >>> logger = structlog.get_logger()
        >>> logger.info("Hello %s", "World")
        {"event": "Hello World"}

        Use write-only to skip production of logs:

        >>> logger = structlog.get_logger()
        >>> logger.info("Hello World", write_only=True) # Not produced to ClickHouse
        {"event": "Hello World"}

        Similary, use produce-only to only produce logs to ClickHouse:

        >>> logger = structlog.get_logger()
        >>> logger.info("Hello World", produce_only=True) # Nothing is written!

        Async variants of all methods:

        >>> logger = structlog.get_logger()
        >>> await logger.ainfo("Hello World")

        Do **NOT** use in workflow context! Async variants run in a separate thread, and
        Temporal does not allow threads to be spawned in workflow context!
    """

    debug = _make_method("debug")
    adebug = _make_async_method("debug")

    info = _make_method("info")
    ainfo = _make_async_method("info")

    warning = warn = _make_method("warning")
    awarning = awarn = _make_async_method("warning")

    error = _make_method("error")
    aerror = _make_async_method("error")

    exception = _make_method("exception")
    aexception = _make_async_method("exception")

    critical = fatal = _make_method("critical")
    acritical = afatal = _make_async_method("critical")

    def log(self, level, event, *args, **kwargs) -> typing.Any:
        name = LEVEL_TO_NAME[level]
        event = _format_args(event, *args)

        if name == "exception":
            kwargs = _set_exc_info(async_method=False, **kwargs)
            method_name = "error"
        else:
            method_name = name

        return self._proxy_to_logger(method_name, event, **kwargs)

    async def alog(self, level, event, *args, **kwargs) -> typing.Any:
        name = LEVEL_TO_NAME[level]

        event = _format_args(event, *args)

        if name == "exception" or name == "error":
            kwargs = _set_exc_info(async_method=True, **kwargs)
            method_name = "error"
        else:
            method_name = name

        scs_token = structlog.contextvars._ASYNC_CALLING_STACK.set(sys._getframe().f_back)  # type: ignore[arg-type]
        ctx = contextvars.copy_context()

        try:
            return await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: ctx.run(lambda: self._proxy_to_logger(method_name, event, **kwargs)),
            )
        finally:
            structlog.contextvars._ASYNC_CALLING_STACK.reset(scs_token)


def merge_temporal_context(
    logger: structlog.typing.WrappedLogger, method_name: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    """A processor that merges Temporal context into the `event_dict`.

    This works for both context in a workflow and in an activity.
    """
    if temporalio.activity.in_activity():
        ctx = get_temporal_activity_context()

        for k, v in ctx.items():
            event_dict.setdefault(k, v)

    elif temporalio.workflow.in_workflow():
        ctx = get_temporal_workflow_context()

        for k, v in ctx.items():
            event_dict.setdefault(k, v)

    return event_dict


def filter_by_level(logger: Logger, method_name: str, event_dict: structlog.typing.EventDict):
    """Filter logs by level when appropiate.

    We only filter logs by level when going to a `WriteOnlyLogger`, as all log levels
    are produced when possible. This allows a performance boost when only writing logs
    by raising the log level.
    """
    level = event_dict.get("level", None)

    if not level or not isinstance(logger, WriteOnlyLogger):
        return event_dict

    if NAME_TO_LEVEL[level] >= NAME_TO_LEVEL[settings.TEMPORAL_LOG_LEVEL.lower()]:
        return event_dict

    raise structlog.DropEvent


def configure_logger(
    extra_processors: list[structlog.types.Processor] | None = None,
    queue: LogQueue | None = None,
    producer: aiokafka.AIOKafkaProducer | None = None,
    cache_logger_on_first_use: bool = True,
    loop: asyncio.AbstractEventLoop | None = None,
    file: typing.TextIO | None = None,
) -> None:
    """Configure a structlog for Temporal workflows.

    Configuring the logger involves:
    * Setting up processors.
    * Spawning a task to listen for Kafka logs.
    * Spawning a task to shutdown gracefully on worker shutdown.

    Examples:

        Except for perhaps unit tests, this should be called only once when
        starting a Temporal worker. The loop running the temporal worker should
        be passed as the `loop` argument.

        >>> with asyncio.Runner() as runner:
        ...     loop = runner.get_loop()
        ...     configure_logger(loop=loop)

    Args:
        logger_factory: Optionally, override the default `logger_factory`.
        extra_processors: Optionally, add any processors at the end of the chain.
        queue: Optionally, bring your own log queue.
        producer: Optionally, bring your own Kafka producer.
        cache_logger_on_first_use: Set whether to cache logger for performance.
            Should always be `True` except in tests.
        loop: The loop where the aforementioned tasks will run on.
    """
    base_processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        filter_by_level,
        structlog.contextvars.merge_contextvars,
        merge_temporal_context,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f", utc=True),
        structlog.stdlib.add_logger_name,
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            },
            additional_ignores=["posthog.temporal.common.logger", "WrapperLogger"],
        ),
    ]

    log_queue = queue if queue is not None else asyncio.Queue(maxsize=0)
    log_producer = None
    log_producer_error = None

    is_test_or_tty = sys.stderr.isatty() or settings.TEST

    if is_test_or_tty:
        logger_factory = LoggerFactory(file=file, is_test_or_tty=is_test_or_tty)
        base_processors += [
            EventRenamer("msg"),
            structlog.dev.ConsoleRenderer(event_key="msg"),
        ]
    else:
        try:
            log_producer = KafkaLogProducerFromQueueAsync(
                queue=log_queue, topic=KAFKA_LOG_ENTRIES, producer=producer, loop=loop
            )
        except Exception as e:
            # Skip putting logs in queue if we don't have a producer that can consume the queue.
            # We save the error to log it later as the logger hasn't yet been configured at this time.
            log_producer_error = e
            logger_factory = LoggerFactory(file=file, is_test_or_tty=is_test_or_tty)
        else:
            logger_factory = LoggerFactory(
                loop=loop or asyncio.get_running_loop(), queue=log_queue, file=file, is_test_or_tty=is_test_or_tty
            )

        base_processors += [
            structlog.processors.dict_tracebacks,
            EventRenamer("msg"),
            LogMessagesRenderer(event_key="msg"),
        ]

    extra_processors_to_add = extra_processors if extra_processors is not None else []

    # The Django logger may have ran configure before us.
    # Ensure we start from a clean slate.
    structlog.reset_defaults()
    structlog.configure(
        processors=base_processors + extra_processors_to_add,
        logger_factory=logger_factory,
        wrapper_class=WrapperLogger,
        cache_logger_on_first_use=cache_logger_on_first_use,
    )

    if log_producer is None:
        if loop is not None:
            logger = structlog.get_logger()
            logger.error("Failed to initialize log producer", exc_info=log_producer_error)
        return

    listen_task = create_background_task(
        log_producer.listen(), loop or asyncio.get_running_loop(), name="log_producer_listen"
    )

    async def handle_worker_shutdown():
        """Gracefully handle a Temporal Worker shutting down.

        Graceful handling means:
        * Waiting until the queue is fully processed to avoid missing log messages.
        * Cancel task listening on queue.
        """
        await temporalio.activity.wait_for_worker_shutdown()

        await log_queue.join()

        listen_task.cancel()

        await asyncio.wait([listen_task])

    create_background_task(handle_worker_shutdown(), loop or asyncio.get_running_loop(), name="handle_worker_shutdown")


CoroRetType = typing.TypeVar("CoroRetType")


def create_background_task(
    coro: collections.abc.Coroutine[typing.Any, typing.Any, CoroRetType],
    loop: asyncio.AbstractEventLoop,
    name: str | None = None,
) -> asyncio.Task[CoroRetType]:
    """Wrap coro in a task and add them to BACKGROUND_LOGGER_TASKS.

    Adding them to BACKGROUND_LOGGER_TASKS keeps a strong reference to the task, so they
    won't be garbage collected and disappear mid execution.

    This function also prevents multiple tasks with the same name to be scheduled. This
    is used to prevent multiple log producers from starting, in case logging is
    accidentally configured more than once.
    """
    if name is not None and name in BACKGROUND_LOGGER_TASKS:
        return BACKGROUND_LOGGER_TASKS[name]

    new_task = loop.create_task(coro, name=name)
    BACKGROUND_LOGGER_TASKS[new_task.get_name()] = new_task

    def delitem(task: asyncio.Task[CoroRetType]):
        del BACKGROUND_LOGGER_TASKS[task.get_name()]

    new_task.add_done_callback(delitem)

    return new_task


class KafkaLogProducerFromQueueAsync:
    """Produce log messages to Kafka by getting them from a queue.

    This KafkaLogProducerFromQueueAsync was designed to ingest logs into the ClickHouse log_entries table.
    For this reason, the messages we produce to Kafka are serialized as JSON in the schema expected by
    the log_entries table. Eventually, we could de-couple this producer from the table schema, but
    schema changes are rare in ClickHouse, and for now we are only using this for logs, so the tight
    coupling is preferred over the extra complexity of de-coupling this producer.

    Attributes:
        queue: The queue we are listening to get log event_dicts to serialize and produce.
        topic: The topic to produce to. This should be left to the default KAFKA_LOG_ENTRIES.
        key: The key for Kafka partitioning. Default to None for random partition.
        producer: Optionally, bring your own aiokafka.AIOKafkaProducer. This is mostly here for testing.
    """

    def __init__(
        self,
        queue: asyncio.Queue[bytes],
        topic: str = KAFKA_LOG_ENTRIES,
        key: str | None = None,
        producer: aiokafka.AIOKafkaProducer | None = None,
        loop: None | asyncio.AbstractEventLoop = None,
    ):
        self.queue = queue
        self.topic = topic
        self.key = key
        self.producer = (
            producer
            if producer is not None
            else aiokafka.AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_HOSTS,
                security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
                acks="all",
                api_version="2.5.0",
                ssl_context=configure_default_ssl_context() if settings.KAFKA_SECURITY_PROTOCOL == "SSL" else None,
                loop=loop,
            )
        )
        self.logger = structlog.get_logger("posthog.temporal.common.logger.KafkaLogProducerFromQueueAsync")

    async def listen(self):
        """Listen to messages in queue and produce them to Kafka as they come.

        This is designed to be ran as an asyncio.Task, as it will wait forever for the queue
        to have messages.
        """
        await self.producer.start()
        try:
            while True:
                msg = await self.queue.get()
                await self.produce(msg)

        finally:
            await self.flush()
            await self.producer.stop()

    async def produce(self, msg: bytes):
        """Produce messages to configured topic and key.

        We catch any exceptions so as to continue processing the queue even if the broker is unavailable
        or we fail to produce for whatever other reason. We log the failure to not fail silently.
        """
        fut = await self.producer.send(self.topic, msg, key=self.key)
        fut.add_done_callback(self.mark_queue_done)

        try:
            await fut
        except Exception:
            self.logger.exception("Failed to produce log to Kafka topic %s", self.topic)
            self.logger.debug("Message that couldn't be produced to Kafka topic %s: %s", self.topic, msg)

    async def flush(self):
        try:
            await self.producer.flush()
        except Exception:
            self.logger.exception("Failed to flush producer")

    def mark_queue_done(self, _=None):
        self.queue.task_done()


def configure_default_ssl_context():
    """Setup a default SSL context for Kafka."""
    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_OPTIONAL
    context.load_default_certs()
    return context


def get_temporal_activity_context() -> dict[str, str | int]:
    """Return activity context variables from Temporal.

    More specifically, the context variables coming from Temporal are:
    * activity_id: The current activity's ID.
    * activity_type: The current activity's type.
    * attempt: The current attempt number of the activity.
    * task_queue: The task queue this workflow is running on.
    * workflow_id: The ID of the workflow running this activity.
    * workflow_namespace: The namespace the workflow is running on.
    * workflow_run_id: The ID of the workflow execution running this activity. This can
        be thought of as the 'instance' of the workflow.
    * workflow_type: The type of workflow running this activity.

    We attempt to fetch the context from the activity information. If undefined, an empty dict
    is returned. When running this in an activity, the context will be defined.
    """
    activity_info = try_activity_info()

    if activity_info is None:
        return {}

    ctx: dict[str, str | int] = {
        "activity_id": activity_info.activity_id,
        "activity_type": activity_info.activity_type,
        "attempt": activity_info.attempt,
        "task_queue": activity_info.task_queue,
        "workflow_id": activity_info.workflow_id,
        "workflow_namespace": activity_info.workflow_namespace,
        "workflow_run_id": activity_info.workflow_run_id,
        "workflow_type": activity_info.workflow_type,
    }

    return ctx


def get_temporal_workflow_context() -> dict[str, str | int]:
    """Return workflow context variables from Temporal.

    More specifically, the context variables coming from Temporal are:
    * attempt: The current attempt number of the workflow.
    * task_queue: The task queue this workflow is running on.
    * workflow_id: The ID of the workflow.
    * workflow_namespace: The namespace the workflow is running on.
    * workflow_run_id: The ID of the Temporal Workflow Execution running the workflow.
    * workflow_type: The name of the workflow

    We attempt to fetch the context from the workflow information. If undefined, an empty dict
    is returned. When running this in a workflow, the context will be defined.
    """
    workflow_info = try_workflow_info()

    if workflow_info is None:
        return {}

    ctx: dict[str, str | int] = {
        "attempt": workflow_info.attempt,
        "task_queue": workflow_info.task_queue,
        "workflow_id": workflow_info.workflow_id,
        "workflow_namespace": workflow_info.namespace,
        "workflow_run_id": workflow_info.run_id,
        "workflow_type": workflow_info.workflow_type,
    }

    return ctx


def try_activity_info() -> temporalio.activity.Info | None:
    """Attempt to obtain activity information from context.

    Returns:
        None if calling outside an activity, else the temporalio.activity.Info instance
        associated with this context.
    """
    try:
        activity_info = temporalio.activity.info()
    except RuntimeError:
        return None
    else:
        return activity_info


def try_workflow_info() -> temporalio.workflow.Info | None:
    """Attempt to obtain workflow information from context.

    Returns:
        None if calling outside a workflow, else the temporalio.workflow.Info instance
        associated with this context.
    """
    try:
        workflow_info = temporalio.workflow.info()
    except RuntimeError:
        return None
    else:
        return workflow_info


BATCH_EXPORT_WORKFLOW_TYPES = {
    "s3-export",
    "bigquery-export",
    "snowflake-export",
    "postgres-export",
    "http-export",
    "redshift-export",
    "databricks-export",
}


def resolve_log_source(workflow_type: str, workflow_id: str) -> tuple[str | None, str | None]:
    """Resolves `log_source` and `log_source_id` from workflow parameters.

    This function is used to resolve parameters for ingesting logs into the
    `log_entries` table.

    When a new product/feature is developed, a new branch should be added in this
    function if logs are to be produced correctly to `log_entries`.

    The resolution is fairly hard-coded as every product/feature defines its own
    `log_source` and `log_source_id`. So, we concentrate the hard-coded resolution here
    to make it easy to find and update.

    Returns:
        A tuple of strings, if we could resolve `log_source` and `log_source_id` else a
        tuple of `None`.
    """
    log_source_id: str | None = None
    log_source: str | None = None

    if workflow_type == "backfill-batch-export":
        # This works because the WorkflowID is made up like f"{batch_export_id}-Backfill-{data_interval_end}"
        log_source_id = workflow_id.split("-Backfill")[0]
        log_source = "batch_exports_backfill"
    elif workflow_type == "external-data-job":
        # This works because the WorkflowID is made up like f"{external_data_schema_id}-{data_interval_end}"
        log_source_id = workflow_id.rsplit("-", maxsplit=3)[0]
        log_source = "external_data_jobs"
    elif workflow_type == "data-modeling-run":
        # This works because the WorkflowID is made up like f"{saved_query_id}-{data_interval_end}"
        log_source_id = workflow_id.rsplit("-", maxsplit=3)[0]
        log_source = "data_modeling_run"
    elif workflow_type in BATCH_EXPORT_WORKFLOW_TYPES:
        # This works because the WorkflowID is made up like f"{batch_export_id}-{data_interval_end}"
        # Since 'data_interval_end' is an iso formatted datetime string, it has two '-' to separate the
        # date. Plus one more leaves us at the end of right at the end of 'batch_export_id'.
        log_source_id = workflow_id.rsplit("-", maxsplit=3)[0]
        log_source = "batch_exports"

    return (log_source, log_source_id)
