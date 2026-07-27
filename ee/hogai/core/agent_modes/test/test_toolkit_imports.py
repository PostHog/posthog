import pkgutil
import importlib

from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

import ee.hogai.core.agent_modes.presets as presets_package
from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit


def _discover_toolkit_classes() -> list[tuple[str, type[AgentToolkit]]]:
    """Every toolkit class reachable from a preset AgentModeDefinition.

    Toolkits load their tools via lazy `from products... import` inside the
    `tools` property, so a renamed or moved module is invisible until that
    property runs at runtime. Discovering the classes here lets the test below
    force those imports — new presets are covered automatically.
    """
    toolkit_classes: dict[str, type[AgentToolkit]] = {}
    for module_info in pkgutil.iter_modules(presets_package.__path__):
        if module_info.name == "test":
            continue
        module = importlib.import_module(f"{presets_package.__name__}.{module_info.name}")
        for definition in vars(module).values():
            if isinstance(definition, AgentModeDefinition):
                toolkit_classes.setdefault(definition.toolkit_class.__name__, definition.toolkit_class)
    return sorted(toolkit_classes.items())


class TestToolkitImports(BaseTest):
    @parameterized.expand(_discover_toolkit_classes())
    def test_toolkit_tools_property_imports_resolve(self, _name: str, toolkit_class: type[AgentToolkit]) -> None:
        context_manager = AssistantContextManager(
            team=self.team, user=self.user, config=RunnableConfig(configurable={})
        )
        toolkit = toolkit_class(team=self.team, user=self.user, context_manager=context_manager)
        # Accessing `.tools` runs the lazy imports; a stale import raises here.
        assert isinstance(toolkit.tools, list)

    def test_discovers_toolkits(self) -> None:
        assert len(_discover_toolkit_classes()) > 0
