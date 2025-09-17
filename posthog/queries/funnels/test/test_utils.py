from posthog.test.base import BaseTest

from posthog.constants import FunnelOrderType
from posthog.models.filters import Filter
from posthog.queries.funnels import ClickhouseFunnel, ClickhouseFunnelStrict, ClickhouseFunnelUnordered
from posthog.queries.funnels.utils import get_funnel_order_class


class TestGetFunnelOrderClass(BaseTest):
    def test_filter_missing_order(self):
        filter = Filter({"foo": "bar"})
        self.assertEqual(get_funnel_order_class(filter), ClickhouseFunnel)

    def test_unordered(self):
        filter = Filter({"funnel_order_type": FunnelOrderType.UNORDERED})
        self.assertEqual(get_funnel_order_class(filter), ClickhouseFunnelUnordered)

    def test_strict(self):
        filter = Filter({"funnel_order_type": FunnelOrderType.STRICT})
        self.assertEqual(get_funnel_order_class(filter), ClickhouseFunnelStrict)

    def test_ordered(self):
        filter = Filter({"funnel_order_type": FunnelOrderType.ORDERED})
        self.assertEqual(get_funnel_order_class(filter), ClickhouseFunnel)
