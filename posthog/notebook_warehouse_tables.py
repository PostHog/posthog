"""Hooks for publishing notebook dataframes and reporting their warehouse lineage.

The storage and lineage owners register their implementations during Django startup. Loading them
on first use keeps the warehouse clients off the startup path for every Django process.
"""

from collections.abc import Callable, Sequence
from dataclasses import field
from typing import TYPE_CHECKING, Any, Protocol

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.activity_logging.utils import ActivityCredential


class NotebookTableError(Exception):
    """A notebook can't write the warehouse table it asked for. The message is user-facing."""


@frozen
class NotebookTableUpload:
    url: str
    fields: dict[str, str] = field(repr=False)


@frozen
class NotebookTableAttribution:
    created_via: str
    credential: "ActivityCredential | None"

    @classmethod
    def from_json(cls, value: dict[str, Any] | None) -> "NotebookTableAttribution | None":
        from posthog.models.activity_logging.utils import ActivityCredential

        if value is None:
            return None
        credential = value.get("credential")
        return cls(
            created_via=value["created_via"], credential=ActivityCredential(**credential) if credential else None
        )


class NotebookTableWriter(Protocol):
    def table_created_via(self, event_source: str, is_self_driving_wizard: bool) -> str: ...
    def validate_notebook_table_name(self, team_id: int, table_name: str, user_id: int | None) -> None: ...
    def lock_notebook_table_version(self, team_id: int, table_name: str, table_id: str, run_id: str) -> bool: ...
    def presign_notebook_table_upload(self, team_id: int, table_name: str, run_id: str) -> NotebookTableUpload: ...
    def save_notebook_table(
        self,
        team_id: int,
        table_name: str,
        user_id: int | None,
        run_id: str,
        attribution: NotebookTableAttribution | None = None,
    ) -> str: ...


NotebookTableLineageSync = Callable[[int, str, str, Sequence[str], str, str, str], list[str]]

_load_writer: Callable[[], NotebookTableWriter] | None = None
_load_lineage_sync: Callable[[], NotebookTableLineageSync] | None = None


def register_notebook_table_writer(load: Callable[[], NotebookTableWriter]) -> None:
    global _load_writer
    _load_writer = load


def get_notebook_table_writer() -> NotebookTableWriter:
    if _load_writer is None:
        raise RuntimeError("The notebook table writer is not registered.")
    return _load_writer()


def register_notebook_table_lineage_sync(load: Callable[[], NotebookTableLineageSync]) -> None:
    global _load_lineage_sync
    _load_lineage_sync = load


def sync_notebook_table_to_dag(
    team_id: int,
    table_name: str,
    warehouse_table_id: str,
    upstream_queries: Sequence[str],
    notebook_short_id: str,
    notebook_node_id: str,
    run_id: str,
) -> list[str]:
    if _load_lineage_sync is None:
        raise RuntimeError("Notebook table lineage sync is not registered.")
    sync = _load_lineage_sync()
    return sync(team_id, table_name, warehouse_table_id, upstream_queries, notebook_short_id, notebook_node_id, run_id)
