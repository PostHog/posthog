import re
import sys
import pkgutil
import importlib
from pathlib import Path

from django.apps import apps
from django.utils.module_loading import module_has_submodule

import structlog

from posthog.admin.console.moved import MovedAction, MovedPage, MovedRecordResolver
from posthog.admin.console.panels import Owner, Panel
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.tools import ConsoleTool

# Navigation headings. Add one here, in the shell, only when no existing group fits a new tool.
TOOL_GROUPS = frozenset({"Data", "Incidents", "Billing", "Organizations", "Access"})
KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PK_PARAMETER = re.compile(r"<(?:\w+:)?pk>")
# A shell module whose name ends in one of these registers panels, tools or moved URLs, and discover() imports it.
CONTRIBUTION_SUFFIXES = ("_panels", "_tool", "_tools")

logger = structlog.get_logger(__name__)


def _check_metadata(kind: str, cls: type, key: str, title: str) -> None:
    if not KEY_PATTERN.match(key):
        raise ValueError(f"Console {kind} {cls.__name__} needs a lowercase, dash-separated key, not {key!r}")
    if not title.strip():
        raise ValueError(f"Console {kind} {cls.__name__} needs a title")


def _qualified_name(declared: object) -> str | None:
    if declared is None:
        return None
    return f"{getattr(declared, '__module__', '')}.{getattr(declared, '__qualname__', '')}"


def _caller_module() -> str:
    # The module that called register_moved_action or register_moved_page: two frames up from here.
    return sys._getframe(2).f_globals.get("__name__", "")


def _same_declaration(existing: object, new: object) -> bool:
    # A contribution module that raised during discover() runs again on the next call, which registers new class and
    # function objects for the same declarations. Comparing names instead of identity lets that retry raise the
    # module's real error, not a duplicate-key error.
    if isinstance(existing, MovedAction) and isinstance(new, MovedAction):
        return (existing.record, existing.target, _qualified_name(existing.resolver)) == (
            new.record,
            new.target,
            _qualified_name(new.resolver),
        )
    if isinstance(existing, MovedPage) and isinstance(new, MovedPage):
        return existing == new
    return _qualified_name(existing) == _qualified_name(new)


class ConsoleRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, dict[str, type[Panel]]] = {record: {} for record in RECORD_TYPES}
        self._tools: dict[str, type[ConsoleTool]] = {}
        self._moved: dict[str, MovedAction | MovedPage] = {}
        # The module that declared each moved URL, so a module that fails during discover() loses only its own.
        self._moved_modules: dict[str, str] = {}
        self._discovered = False

    def register_panel(self, panel_class: type[Panel]) -> type[Panel]:
        _check_metadata("panel", panel_class, panel_class.key, panel_class.title)
        if panel_class.record not in RECORD_TYPES:
            raise ValueError(f"Unknown console record type {panel_class.record!r} on {panel_class.__name__}")
        panels = self._panels[panel_class.record]
        existing = panels.get(panel_class.key)
        if existing is not None and not _same_declaration(existing, panel_class):
            raise ValueError(f"Console panel key {panel_class.key!r} is already used by {existing.__name__}")
        panels[panel_class.key] = panel_class
        return panel_class

    def panels_for(self, record: str) -> list[Panel]:
        self.discover()
        # Danger panels go last, so destructive actions always sit at the bottom of a page.
        classes = sorted(
            self._panels[record].values(),
            key=lambda panel_class: (panel_class.danger, panel_class.order, panel_class.title),
        )
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
        if existing is not None and not _same_declaration(existing, tool_class):
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

    def _register_moved(self, moved: MovedAction | MovedPage, module: str) -> None:
        # Every console route sits under /admin/, so AdminOAuth2Middleware adds its Google step-up to old URLs too.
        if not moved.old_path.startswith("admin/") or moved.old_path.startswith("admin/console/"):
            raise ValueError(f"Moved URL {moved.old_path!r} must be an old Django admin path under admin/")
        existing = self._moved.get(moved.old_path)
        if existing is not None and not _same_declaration(existing, moved):
            raise ValueError(f"Moved URL {moved.old_path!r} is already registered")
        self._moved[moved.old_path] = moved
        self._moved_modules[moved.old_path] = module

    def register_moved_action(
        self, *, old_path: str, record: str, target: str, resolver: MovedRecordResolver | None = None
    ) -> None:
        """Redirect the old Django admin URL of a record action to where it lives on the console record page."""
        if record not in RECORD_TYPES:
            raise ValueError(f"Unknown console record type {record!r} for moved URL {old_path!r}")
        if resolver is None and not PK_PARAMETER.search(old_path):
            raise ValueError(f"Moved URL {old_path!r} needs a <pk> path parameter, or a resolver that finds the record")
        self._register_moved(
            MovedAction(old_path=old_path, record=record, target=target, resolver=resolver), _caller_module()
        )

    def register_moved_page(self, *, old_path: str, title: str, url: str, note: str = "") -> None:
        """Redirect the old URL of a Django admin page to the console page that replaced it."""
        if not url.startswith("/admin/console/"):
            raise ValueError(f"Moved URL {old_path!r} must lead to a console page, not {url!r}")
        self._register_moved(MovedPage(old_path=old_path, title=title, url=url, note=note), _caller_module())

    def moved(self) -> list[MovedAction | MovedPage]:
        self.discover()
        return list(self._moved.values())

    def owners(self) -> set[Owner]:
        self.discover()
        panel_owners = {panel_class.owner for panels in self._panels.values() for panel_class in panels.values()}
        return panel_owners | {tool_class.owner for tool_class in self._tools.values()}

    def staff_groups(self) -> set[str]:
        return {owner.staff_group for owner in self.owners() if owner.staff_group is not None}

    def contribution_modules(self) -> list[str]:
        shell_modules = [
            f"{__package__}.{module.name}"
            for module in sorted(pkgutil.iter_modules([str(Path(__file__).parent)]), key=lambda module: module.name)
            if module.name.endswith(CONTRIBUTION_SUFFIXES)
        ]
        app_modules = [
            f"{app_config.name}.console"
            for app_config in apps.get_app_configs()
            if module_has_submodule(app_config.module, "console")
        ]
        return shell_modules + app_modules

    def discover(self) -> None:
        if self._discovered:
            return
        # Each module imports on its own, so one that raises drops only its own panels, tools and moved URLs, including
        # any it registered before raising, so no half-built panel reaches a record page. It stays out until the
        # process restarts, and the error log names it.
        for module_name in self.contribution_modules():
            try:
                importlib.import_module(module_name)
            except Exception:
                logger.exception("admin_console_contribution_failed", module=module_name)
                self._forget_module(module_name)
        self._discovered = True

    def _forget_module(self, module_name: str) -> None:
        # Only what the failed module declared itself goes. A healthy module it imported on the way stays registered,
        # because Python keeps that import and discover() would not register it again.
        for panels in self._panels.values():
            for key in [key for key, panel_class in panels.items() if panel_class.__module__ == module_name]:
                del panels[key]
        for key in [key for key, tool_class in self._tools.items() if tool_class.__module__ == module_name]:
            del self._tools[key]
        for old_path in [path for path, module in self._moved_modules.items() if module == module_name]:
            del self._moved[old_path]
            del self._moved_modules[old_path]


console = ConsoleRegistry()
