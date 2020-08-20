from django_clickhouse.clickhouse_models import ClickHouseModel
from django_clickhouse.engines import MergeTree
from infi.clickhouse_orm import fields


class ClickHouseEvent(ClickHouseModel):
    id = fields.UInt32Field()
    team_id = fields.UInt32Field()
    event = fields.StringField()
    distinct_id = fields.StringField()
    timestamp = fields.DateTime64Field()
    elements_hash = fields.NullableField(fields.StringField())

    engine = MergeTree("timestamp", ("event", "distinct_id"))
