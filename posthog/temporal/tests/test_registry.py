import sys
from types import ModuleType

import pytest

from temporalio import activity, workflow

from posthog.temporal.registry import WorkerBagCollector, WorkerBagSource


@workflow.defn
class ExampleWorkflow:
    @workflow.run
    async def run(self) -> None:
        pass


class InheritedWorkflow(ExampleWorkflow):
    pass


@activity.defn
async def example_activity() -> None:
    pass


class ActivityOwner:
    @activity.defn
    async def bound_activity(self) -> None:
        pass


def install_module(monkeypatch: pytest.MonkeyPatch, name: str, **members: object) -> ModuleType:
    module = ModuleType(name)
    vars(module).update(members)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.mark.parametrize("names", [(), ("SELECTED",)])
def test_collect_selects_definitions(monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]) -> None:
    bound_activity = ActivityOwner().bound_activity
    module = install_module(
        monkeypatch,
        "registry_selection",
        workflow=ExampleWorkflow,
        inherited=InheritedWorkflow,
        activity=example_activity,
        bound_activity=bound_activity,
        unrelated=object(),
        SELECTED=[ExampleWorkflow, bound_activity],
    )
    collector = WorkerBagCollector((WorkerBagSource(modules=(module.__name__,), task_queues=("queue",), names=names),))

    bag = collector.collect("queue")

    assert set(bag.workflows) == {ExampleWorkflow}
    assert set(bag.activities) == ({bound_activity} if names else {bound_activity, example_activity})


@pytest.mark.parametrize("names", [(), ("WORKFLOWS", "ACTIVITIES")])
def test_collect_combines_sources_without_importing_other_queues(
    monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]
) -> None:
    workflows = install_module(
        monkeypatch,
        "registry_workflows",
        workflow=ExampleWorkflow,
        alias=ExampleWorkflow,
        WORKFLOWS=[ExampleWorkflow, ExampleWorkflow],
    )
    activities = install_module(
        monkeypatch,
        "registry_activities",
        activity=example_activity,
        ACTIVITIES=[example_activity],
    )
    collector = WorkerBagCollector(
        (
            WorkerBagSource(modules=(workflows.__name__,), task_queues=("queue", "other-queue"), names=names),
            WorkerBagSource(modules=(workflows.__name__, activities.__name__), task_queues=("queue",), names=names),
            WorkerBagSource(modules=("registry_module_that_does_not_exist",), task_queues=("unrelated-queue",)),
        )
    )

    bag = collector.collect("queue")

    assert bag.workflows == (ExampleWorkflow,)
    assert bag.activities == (example_activity,)
    other_bag = collector.collect("other-queue")
    assert other_bag.workflows == (ExampleWorkflow,)
    assert other_bag.activities == ()


@pytest.mark.parametrize(
    "module_name,names,task_queue,error,match",
    [
        ("registry_missing_module", (), "queue", ModuleNotFoundError, "registry_missing_module"),
        ("registry_empty", (), "queue", ValueError, "registry_empty"),
        ("registry_workflows", ("ACTIVITIES", "WORKFLOW_TYPO"), "queue", ValueError, "registry_workflows"),
        ("registry_workflows", (), "unknown-queue", ValueError, "No sources registered"),
    ],
)
def test_collect_rejects_invalid_sources(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    names: tuple[str, ...],
    task_queue: str,
    error: type[Exception],
    match: str,
) -> None:
    valid = install_module(monkeypatch, "registry_valid", activity=example_activity, ACTIVITIES=[example_activity])
    install_module(monkeypatch, "registry_empty", unrelated=object())
    install_module(monkeypatch, "registry_workflows", workflow=ExampleWorkflow, WORKFLOWS=[ExampleWorkflow])
    collector = WorkerBagCollector(
        (
            WorkerBagSource(modules=(valid.__name__,), task_queues=("queue",)),
            WorkerBagSource(modules=(valid.__name__, module_name), task_queues=("queue",), names=names),
        )
    )

    with pytest.raises(error, match=match):
        collector.collect(task_queue)
