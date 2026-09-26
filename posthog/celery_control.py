"""Remote control commands that tolerate a worker with no event dispatcher.

A worker started with ``--without-gossip --without-heartbeat`` and no ``--task-events``
never starts Celery's ``Events`` bootstep, so ``consumer.event_dispatcher`` stays None for
the life of the process. Celery's own handlers for the event commands dereference it, and
a monitor that broadcasts one of them on a timer turns that into an endless error loop.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from celery.worker.control import Panel, control_command, ok

EVENTS_DISABLED_REPLY = "events are disabled on this worker"

EVENT_DISPATCHER_COMMANDS = ("enable_events", "disable_events", "heartbeat")


def _guard_missing_event_dispatcher(handler: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(handler)
    def guarded(state: Any, *args: Any, **kwargs: Any) -> Any:
        if state.consumer.event_dispatcher is None:
            return ok(EVENTS_DISABLED_REPLY)
        return handler(state, *args, **kwargs)

    return guarded


def register_event_dispatcher_guards() -> None:
    """Replace the event commands in Celery's global panel with guarded versions."""
    for name in EVENT_DISPATCHER_COMMANDS:
        control_command(name=name)(_guard_missing_event_dispatcher(Panel.data[name]))
