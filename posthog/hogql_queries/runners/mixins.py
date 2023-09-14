from functools import cached_property

from posthog.models.filters.mixins.utils import include_dict
from posthog.types import InsightQueryNode


class BaseQueryMixing:
    query: InsightQueryNode


class FilterTestAccountsMixin(BaseQueryMixing):
    @cached_property
    def filter_test_accounts(self) -> bool:
        return self.query.filterTestAccounts or True  # TODO: Should we default to false?

    @include_dict
    def filter_test_accounts_to_dict(self):
        return {"filter_test_accounts": self.filter_test_accounts} if self.filter_test_accounts else {}
