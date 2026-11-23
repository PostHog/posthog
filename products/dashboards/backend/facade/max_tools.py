"""Facade re-exports for dashboards Max tools.

The assistant's agent-mode presets register these tool classes. Re-exporting them in a
dedicated submodule keeps ``facade/api.py`` free of the heavy ``ee.hogai.tool`` import,
so config-only consumers don't drag it onto the ``django.setup()`` path.
"""

from products.dashboards.backend.max_tools import UpsertDashboardTool

__all__ = [
    "UpsertDashboardTool",
]
