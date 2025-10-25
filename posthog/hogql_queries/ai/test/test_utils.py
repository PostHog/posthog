from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin


class TestTaxonomyUtils(BaseTest):
    def test_is_stale(self):
        class Mixin(TaxonomyCacheMixin):
            team = self.team

        date = timezone.now()

        mixin = Mixin()
        self.assertFalse(mixin._is_stale(last_refresh=date, lazy=False))
        self.assertFalse(mixin._is_stale(last_refresh=date, lazy=True))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=15), lazy=False))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=15), lazy=True))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=59), lazy=True))
        self.assertFalse(mixin._is_stale(last_refresh=date - timedelta(minutes=59), lazy=False))
        self.assertTrue(mixin._is_stale(last_refresh=date - timedelta(minutes=60), lazy=True))
        self.assertTrue(mixin._is_stale(last_refresh=date - timedelta(minutes=60), lazy=False))
