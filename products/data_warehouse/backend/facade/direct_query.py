"""
Direct-query wiring for data_warehouse.

Re-exports the virtual-table builder the HogQL database builder calls for dual-mode
(synced, direct-query-enabled) connections. Its own facade submodule — separate from
``facade.hogql``, which ``database.py`` imports at module level — so the engine helper
modules it pulls stay off the ``django.setup()`` path; consumers import it
function-locally.
"""

from products.data_warehouse.backend.direct_virtual_tables import (
    build_direct_table_for_schema,
    eligible_direct_query_schemas,
)

__all__ = ["build_direct_table_for_schema", "eligible_direct_query_schemas"]
