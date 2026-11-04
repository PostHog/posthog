from django.utils.module_loading import autodiscover_modules

from posthog.admin.console.panels import Panel
from posthog.admin.console.tools import ConsoleTool

RECORD_TYPES = frozenset({"team"})


class ConsoleRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, dict[str, type[Panel]]] = {record: {} for record in RECORD_TYPES}
        self._tools: dict[str, type[ConsoleTool]] = {}
        self._discovered = False

    def register_panel(self, panel_class: type[Panel]) -> type[Panel]:
        if panel_class.record not in RECORD_TYPES:
            raise ValueError(f"Unknown console record type {panel_class.record!r} on {panel_class.__name__}")
        panels = self._panels[panel_class.record]
        existing = panels.get(panel_class.key)
        if existing is not None and existing is not panel_class:
            raise ValueError(f"Console panel key {panel_class.key!r} is already used by {existing.__name__}")
        panels[panel_class.key] = panel_class
        return panel_class

    def panels_for(self, record: str) -> list[Panel]:
        self.discover()
        # Danger panels go last, so destructive actions always sit at the bottom of a page.
        classes = sorted(self._panels[record].values(), key=lambda panel_class: panel_class.danger)
        return [panel_class() for panel_class in classes]

    def get_panel(self, record: str, key: str) -> Panel | None:
        self.discover()
        panel_class = self._panels.get(record, {}).get(key)
        return panel_class() if panel_class else None

    def register_tool(self, tool_class: type[ConsoleTool]) -> type[ConsoleTool]:
        existing = self._tools.get(tool_class.key)
        if existing is not None and existing is not tool_class:
            raise ValueError(f"Console tool key {tool_class.key!r} is already used by {existing.__name__}")
        self._tools[tool_class.key] = tool_class
        return tool_class

    def tools(self) -> list[ConsoleTool]:
        self.discover()
        return [tool_class() for tool_class in sorted(self._tools.values(), key=lambda t: (t.group, t.title))]

    def get_tool(self, key: str) -> ConsoleTool | None:
        self.discover()
        tool_class = self._tools.get(key)
        return tool_class() if tool_class else None

    def discover(self) -> None:
        if self._discovered:
            return
        # Core panels register first, so they lead each page.
        import posthog.admin.console.team_panels  # noqa: F401, PLC0415 — registers the core Team panels
        import posthog.admin.console.events_retention_tool  # noqa: F401, PLC0415 — registers a core tool

        autodiscover_modules("console")
        # Set only after the imports succeed, so a failed import raises again on the next request instead of
        # leaving the console with some panels missing.
        self._discovered = True


console = ConsoleRegistry()
