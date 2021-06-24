from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL


class ClickhouseFunnel(ClickhouseFunnelBase):
    def get_query(self, format_properties):
        return FUNNEL_SQL.format(**format_properties)
