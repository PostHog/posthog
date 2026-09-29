import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

from posthog.hogql.errors import TableAccessDeniedError

# Ambient properties merged into every capture_exception raised within the current execution
# context. Lets a long-running subsystem (e.g. a data warehouse import) tag captured exceptions
# with the job/source they belong to without threading context through every call site. This is
# exception-only and never touches ClickHouse query tags.
_ambient_exception_properties: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar(
    "ambient_exception_properties", default=None
)


def ambient_exception_properties() -> dict[str, object]:
    return _ambient_exception_properties.get() or {}


def bind_exception_context(**properties: object) -> None:
    """Merge properties into the ambient exception context for the current execution context.

    Fire-and-forget: relies on per-task contextvar isolation (temporal activities and celery tasks
    each run in a fresh context), matching how log/query tags are bound at activity entry. Use
    `exception_context` instead when you need the properties scoped and reset (tests, nested spans).
    """
    _ambient_exception_properties.set({**ambient_exception_properties(), **properties})


@contextmanager
def exception_context(**properties: object) -> Iterator[None]:
    """Scope ambient exception properties to a block, resetting them on exit.

    Merges with any properties already in context, so nested contexts accumulate.
    """
    merged = {**ambient_exception_properties(), **properties}
    token = _ambient_exception_properties.set(merged)
    try:
        yield
    finally:
        _ambient_exception_properties.reset(token)


def celery_properties() -> dict:
    try:
        from celery import current_task

        task = current_task
        if task and task.request and task.request.id is not None:
            return {
                "celery_task_name": task.name,
                "celery_task_retries": task.request.retries,
            }
    except Exception:
        pass
    return {}


def find_table_access_denied(error: BaseException | None) -> TableAccessDeniedError | None:
    """Return the TableAccessDeniedError that caused `error`, if any, following the cause chain.

    A denial means the acting user has no access to a table, which is an access control decision
    and not a defect. Callers often wrap it (for example in a Temporal ApplicationError), so the
    top-level type alone is not enough. Only explicit causes (`raise ... from`) count: an error
    raised while handling a denial is a separate failure.
    """
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, TableAccessDeniedError):
            return error
        seen.add(id(error))
        error = error.__cause__
    return None


def capture_exception(error=None, additional_properties=None):
    import structlog
    from posthoganalytics import (
        api_key,
        capture_exception as posthog_capture_exception,
    )

    logger = structlog.get_logger(__name__)

    from posthog.clickhouse.query_tagging import get_query_tags

    properties = get_query_tags().model_dump(exclude_none=True)

    # Ambient context first, then explicit call-site properties so the latter win on collision.
    properties.update(ambient_exception_properties())

    if additional_properties:
        properties.update(additional_properties)

    properties.update(celery_properties())

    denied = find_table_access_denied(error)
    if denied is not None:
        logger.warning(
            "table_access_denied",
            table=denied.table_name,
            error_type=type(error).__name__,
            properties=properties,
        )
        return

    if api_key:
        uuid = posthog_capture_exception(error, properties=properties)

        # Only log if captured
        if uuid is not None:
            logger.exception(error, event_id=uuid)
    else:
        logger.exception(error)
