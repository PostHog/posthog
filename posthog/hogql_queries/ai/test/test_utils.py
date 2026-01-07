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
        assert not mixin._is_stale(last_refresh=date, lazy=False)
        assert not mixin._is_stale(last_refresh=date, lazy=True)
        assert not mixin._is_stale(last_refresh=date - timedelta(minutes=15), lazy=False)
        assert not mixin._is_stale(last_refresh=date - timedelta(minutes=15), lazy=True)
        assert not mixin._is_stale(last_refresh=date - timedelta(minutes=59), lazy=True)
        assert not mixin._is_stale(last_refresh=date - timedelta(minutes=59), lazy=False)
        assert mixin._is_stale(last_refresh=date - timedelta(minutes=60), lazy=True)
        assert mixin._is_stale(last_refresh=date - timedelta(minutes=60), lazy=False)
