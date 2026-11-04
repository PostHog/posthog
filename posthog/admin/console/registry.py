from django.utils.module_loading import autodiscover_modules

from posthog.admin.console.panels import Panel

RECORD_TYPES = frozenset({"team"})


class ConsoleRegistry:
    def __init__(self) -> None:
        self._panels: dict[str, dict[str, type[Panel]]] = {record: {} for record in RECORD_TYPES}
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

    def discover(self) -> None:
        if self._discovered:
            return
        self._discovered = True
        # Core panels register first, so they lead each page.
        import posthog.admin.console.team_panels  # noqa: F401, PLC0415 — registers the core Team panels

        autodiscover_modules("console")


console = ConsoleRegistry()
