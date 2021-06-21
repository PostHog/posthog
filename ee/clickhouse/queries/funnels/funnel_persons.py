from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.sql.funnels.funnel import FUNNEL_PERSONS_SQL


class ClickhouseFunnelPersons(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return FUNNEL_PERSONS_SQL.format(**format_properties)
