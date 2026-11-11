import re

from django.utils.module_loading import autodiscover_modules

from posthog.admin.console.panels import Owner, Panel
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.tools import ConsoleTool

# Navigation headings. Add one here, in the shell, only when no existing group fits a new tool.
TOOL_GROUPS = frozenset({"Data", "Billing", "Organizations", "Access"})
KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _check_metadata(kind: str, cls: type, key: str, title: str) -> None:
    if not KEY_PATTERN.match(key):
        raise ValueError(f"Console {kind} {cls.__name__} needs a lowercase, dash-separated key, not {key!r}")
    if not title.strip():
        raise ValueError(f"Console {kind} {cls.__name__} needs a title")


class ConsoleRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, dict[str, type[Panel]]] = {record: {} for record in RECORD_TYPES}
        self._tools: dict[str, type[ConsoleTool]] = {}
        self._discovered = False

    def register_panel(self, panel_class: type[Panel]) -> type[Panel]:
        _check_metadata("panel", panel_class, panel_class.key, panel_class.title)
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
        _check_metadata("tool", tool_class, tool_class.key, tool_class.title)
        if tool_class.group not in TOOL_GROUPS:
            raise ValueError(
                f"Console tool {tool_class.__name__} uses group {tool_class.group!r}, not one of {sorted(TOOL_GROUPS)}"
            )
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

    def owners(self) -> set[Owner]:
        self.discover()
        panel_owners = {panel_class.owner for panels in self._panels.values() for panel_class in panels.values()}
        return panel_owners | {tool_class.owner for tool_class in self._tools.values()}

    def staff_groups(self) -> set[str]:
        return {owner.staff_group for owner in self.owners() if owner.staff_group is not None}

    def discover(self) -> None:
        if self._discovered:
            return
        # Core panels register first, so they lead each page.
        import posthog.admin.console.oauth_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.redis_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.team_panels  # noqa: F401, PLC0415 — registers the core Team panels
        import posthog.admin.console.tophog_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.user_panels  # noqa: F401, PLC0415 — registers the core User panels
        import posthog.admin.console.api_key_panels  # noqa: F401, PLC0415 — registers the core API key panels
        import posthog.admin.console.project_panels  # noqa: F401, PLC0415 — registers the core Project panels
        import posthog.admin.console.health_checks_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.organization_tools  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.remote_config_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.usage_reports_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.api_key_search_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.organization_panels  # noqa: F401, PLC0415 — registers the core Organization panels
        import posthog.admin.console.events_retention_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.organization_deletion  # noqa: F401, PLC0415 — registers the core Organization deletion panel
        import posthog.admin.console.distinct_id_usage_tool  # noqa: F401, PLC0415 — registers a core tool
        import posthog.admin.console.deletion_request_panels  # noqa: F401, PLC0415 — registers the core deletion request panels
        import posthog.admin.console.conversation_checkpoints_tool  # noqa: F401, PLC0415 — registers a core tool

        autodiscover_modules("console")
        # Set only after the imports succeed, so a failed import raises again on the next request instead of
        # leaving the console with some panels missing.
        self._discovered = True


console = ConsoleRegistry()
