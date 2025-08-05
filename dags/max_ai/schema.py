from pydantic import BaseModel
from pydantic_avro import AvroBase

from posthog.schema import EventTaxonomyItem, TeamTaxonomyItem


# posthog/models/property_definition.py
class PropertyDefinitionSchema(AvroBase):
    name: str
    is_numerical: bool
    property_type: str | None
    type: int
    group_type_index: int | None


# posthog/models/warehouse/table.py
class DataWarehouseTableSchema(AvroBase):
    name: str
    format: str
    columns: list[str]


class PostgresProjectDataSnapshot(BaseModel):
    property_definitions: str
    data_warehouse_tables: str


# posthog/hogql_queries/ai/team_taxonomy_query_runner.py
class TeamTaxonomyItemSchema(AvroBase):
    results: list[TeamTaxonomyItem]


# posthog/hogql_queries/ai/event_taxonomy_query_runner.py
class PropertyTaxonomySchema(AvroBase):
    event: str
    results: list[EventTaxonomyItem]


class ClickhouseProjectDataSnapshot(BaseModel):
    event_taxonomy: str
    properties_taxonomy: str
