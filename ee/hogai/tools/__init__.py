import importlib
from typing import TYPE_CHECKING, Any

# Each tool maps to the submodule that defines it. Resolved lazily via PEP 562 __getattr__
# below, so importing one tool — or this package — does not eagerly pull every tool's
# transitive deps. Notably `create_insight` imports the chat agent, which imports back into
# `ee.hogai.tools`; eager re-exports here formed an import cycle that only survived by
# import-order luck and dragged the whole AI agent core onto the Django startup path.
_TOOL_MODULES: dict[str, str] = {
    "CallMCPServerTool": ".call_mcp_server.tool",
    "CreateFormTool": ".create_form",
    "CreateInsightTool": ".create_insight",
    "CreateNotebookTool": ".create_notebook",
    "ExecuteSQLMCPTool": ".execute_sql.mcp_tool",
    "ExecuteSQLTool": ".execute_sql.tool",
    "ListDataTool": ".list_data",
    "ListFeatureFlagsTool": ".list_feature_flags",
    "ManageMemoriesTool": ".manage_memories",
    "ReadDataTool": ".read_data",
    "ReadDataWarehouseSchemaMCPTool": ".read_data_warehouse_schema.mcp_tool",
    "ReadTaxonomyMCPTool": ".read_taxonomy.mcp_tool",
    "ReadTaxonomyTool": ".read_taxonomy.tool",
    "SearchTool": ".search",
    "SwitchModeTool": ".switch_mode",
    "TaskTool": ".task",
    "TodoWriteTool": ".todo_write",
    "UpsertDashboardTool": ".upsert_dashboard",
}

__all__ = [
    "CallMCPServerTool",
    "CreateFormTool",
    "ManageMemoriesTool",
    "ListDataTool",
    "ListFeatureFlagsTool",
    "ReadDataTool",
    "ReadTaxonomyTool",
    "SearchTool",
    "TaskTool",
    "TodoWriteTool",
    "ExecuteSQLTool",
    "SwitchModeTool",
    "CreateInsightTool",
    "UpsertDashboardTool",
    "CreateNotebookTool",
]


def load_all_tools() -> None:
    """Import every tool submodule so the MCP tools self-register via
    @mcp_tool_registry.register. Called by the registry on demand — registration is
    decoupled from package import so that importing the package (or a single tool) stays
    cheap and cycle-free. Idempotent: re-imports are dict lookups in sys.modules.
    """
    for submodule in dict.fromkeys(_TOOL_MODULES.values()):
        importlib.import_module(submodule, __name__)


def __getattr__(name: str) -> Any:
    submodule = _TOOL_MODULES.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(submodule, __name__)
    return getattr(module, name)


if TYPE_CHECKING:
    from .call_mcp_server.tool import CallMCPServerTool as CallMCPServerTool
    from .create_form import CreateFormTool as CreateFormTool
    from .create_insight import CreateInsightTool as CreateInsightTool
    from .create_notebook import CreateNotebookTool as CreateNotebookTool
    from .execute_sql.mcp_tool import ExecuteSQLMCPTool as ExecuteSQLMCPTool
    from .execute_sql.tool import ExecuteSQLTool as ExecuteSQLTool
    from .list_data import ListDataTool as ListDataTool
    from .list_feature_flags import ListFeatureFlagsTool as ListFeatureFlagsTool
    from .manage_memories import ManageMemoriesTool as ManageMemoriesTool
    from .read_data import ReadDataTool as ReadDataTool
    from .read_data_warehouse_schema.mcp_tool import ReadDataWarehouseSchemaMCPTool as ReadDataWarehouseSchemaMCPTool
    from .read_taxonomy.mcp_tool import ReadTaxonomyMCPTool as ReadTaxonomyMCPTool
    from .read_taxonomy.tool import ReadTaxonomyTool as ReadTaxonomyTool
    from .search import SearchTool as SearchTool
    from .switch_mode import SwitchModeTool as SwitchModeTool
    from .task import TaskTool as TaskTool
    from .todo_write import TodoWriteTool as TodoWriteTool
    from .upsert_dashboard import UpsertDashboardTool as UpsertDashboardTool
