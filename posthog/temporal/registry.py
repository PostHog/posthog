import typing
import importlib
import itertools
import collections.abc

from posthog.dataclasses import frozen


@frozen
class WorkerBagSource:
    """One or more modules to source for one or more task queues.

    Attributes:
        modules: Python module names. Each module is imported to lazy-load
            workflows and activities.
        task_queues: One or more task queues the workflows/activities sourced
            belong to.
        names: When not empty, workflows and activities should be looked up in
            collections from the module matching these names. When empty, they
            are looked up in each module's globals.
    """

    modules: tuple[str, ...]
    task_queues: tuple[str, ...]
    names: tuple[str, ...] = ()


@frozen
class WorkerBag:
    """A bag of workflows and activities.

    Meant to be used to initialize a Temopral Worker.
    """

    workflows: tuple[type, ...] = ()
    activities: tuple[typing.Callable[..., typing.Any], ...] = ()


class WorkerBagCollector:
    """Collects WorkerBags for task queue based on stored sources."""

    def __init__(self, sources: collections.abc.Sequence[WorkerBagSource] = ()) -> None:
        self._sources = tuple(sources)

    def collect(self, task_queue: str, /) -> WorkerBag:
        """Collect a WorkerBag for task_queue.

        Raises:
            ValueError: If there isn't at least one stored source matching the
                given task_queue, and if we don't find anything in a configured
                source's module, as that indicates a configuration error.
        """
        matching = [source for source in self._sources if task_queue in source.task_queues]

        if not matching:
            raise ValueError(f"No sources registered for task queue '{task_queue}'")

        workflows = set()
        activities = set()

        for source in matching:
            for module_name in source.modules:
                module = importlib.import_module(module_name)

                found = False

                obj_iter: collections.abc.Iterable[typing.Any]
                if source.names:
                    obj_iter = itertools.chain.from_iterable(getattr(module, name, ()) for name in source.names)
                else:
                    obj_iter = vars(module).values()

                for obj in obj_iter:
                    if _is_workflow(obj):
                        workflows.add(obj)
                        found = True
                    elif _is_activity(obj):
                        activities.add(obj)
                        found = True

                if not found:
                    raise ValueError(
                        f"Module '{module_name}' contains no workflows or activities. Either the source is wrongly configured, or the module should be removed from the source."
                    )

        return WorkerBag(workflows=tuple(workflows), activities=tuple(activities))


def _is_workflow(any: typing.Any) -> bool:
    """Check if any is a Temporal workflow."""
    return (
        isinstance(any, type)
        and hasattr(any, "__temporal_workflow_definition")
        # Excludes subclasses of Workflows, which Temporal also rejects.
        and any.__temporal_workflow_definition.cls == any
    )


def _is_activity(any: typing.Any) -> bool:
    """Check if any is a Temporal activity."""
    return callable(any) and hasattr(any, "__temporal_activity_definition")
