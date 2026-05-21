import pytest

from django.db.models import Model

from products.data_tools.backend.models.datawarehouse_saved_query_folder import DataWarehouseSavedQueryFolder
from products.data_tools.backend.models.join import DataWarehouseJoin, DataWarehouseViewLink
from products.data_tools.backend.models.query_tab_state import QueryTabState


@pytest.mark.parametrize(
    "model,expected_db_table",
    [
        (DataWarehouseJoin, "posthog_datawarehousejoin"),
        (DataWarehouseSavedQueryFolder, "posthog_datawarehousesavedqueryfolder"),
        (DataWarehouseViewLink, "posthog_datawarehouseviewlink"),
        (QueryTabState, "posthog_querytabstate"),
    ],
)
def test_db_table_preserved_across_split(model: type[Model], expected_db_table: str) -> None:
    """The split moved these models to a new Django app via SeparateDatabaseAndState;
    the `posthog_*` table names must remain unchanged or prod reads break silently."""
    assert model._meta.db_table == expected_db_table
