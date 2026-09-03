"""Where a check's subject can be opened.

A check row carries the subject's id, which is enough to run it but not enough to link to it: a
view is administered on its DAG node and a synced table on its source's schema page. Both are
resolved in bulk for a whole page of checks, never per row -- the overview lists every check in the
project, so a query per row is a query per table in the warehouse.
"""

from collections.abc import Iterable

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade

from ..facade.enums import SubjectType
from ..models import DataQualityCheck


@frozen
class SubjectKey:
    """What identifies a subject across types. Both parts are strings, so they are never positional."""

    subject_type: SubjectType
    subject_uuid: str


@frozen
class SubjectLocation:
    """The ids a subject's detail route needs. All absent when the subject has no such page."""

    node_id: str | None = None
    source_id: str | None = None
    schema_id: str | None = None


def subject_locations(team_id: int, checks: Iterable[DataQualityCheck]) -> dict[SubjectKey, SubjectLocation]:
    """Two queries for any number of checks."""
    view_ids = {str(check.saved_query_id) for check in checks if check.saved_query_id}
    table_ids = {check.table_id for check in checks if check.table_id}

    locations: dict[SubjectKey, SubjectLocation] = {
        SubjectKey(subject_type=SubjectType.VIEW, subject_uuid=saved_query_id): SubjectLocation(node_id=node_id)
        for saved_query_id, node_id in data_modeling_facade.get_node_ids_for_saved_queries(team_id, view_ids).items()
    }
    for table_id, location in warehouse_facade.source_locations_for_tables(team_id, table_ids).items():
        locations[SubjectKey(subject_type=SubjectType.TABLE, subject_uuid=str(table_id))] = SubjectLocation(
            source_id=str(location.source_id), schema_id=str(location.schema_id)
        )
    return locations
