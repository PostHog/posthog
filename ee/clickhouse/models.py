from django_clickhouse.clickhouse_models import ClickHouseModel
from django_clickhouse.engines import MergeTree
from infi.clickhouse_orm import fields

from posthog.models import Event


class ClickHouseEvent(ClickHouseModel):
    id = fields.UInt32Field()
    created_at = fields.DateTime64Field()
    team_id = fields.UInt32Field()
    event = fields.StringField()
    distinct_id = fields.StringField()
    timestamp = fields.DateTime64Field()
    elements_hash = fields.NullableField(fields.StringField())

    engine = MergeTree("timestamp", ("event", "distinct_id"))


class ClickHousePerson(ClickHouseModel):
    id = fields.UInt32Field()
    created_at = fields.DateTime64Field()
    team_id = fields.UInt32Field()

    engine = MergeTree("created_at", ("id",))


class ClickHousePersonDistinctId(ClickHouseModel):
    distinct_id = fields.StringField()
    person_id = fields.UInt32Field()
    team_id = fields.UInt32Field()
    created_at = fields.DateTime64Field()

    engine = MergeTree("created_at", ("person_id",))


class ClickHouseActionEvent(ClickHouseModel):
    action_id = fields.UInt32Field()
    event_id = fields.UInt32Field()
    created_at = fields.DateTime64Field()

    engine = MergeTree("created_at", ("action_id",))
