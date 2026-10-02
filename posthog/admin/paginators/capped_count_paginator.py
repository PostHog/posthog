from django.core.paginator import Paginator
from django.utils.functional import cached_property


class CappedCountPaginator(Paginator):
    """Counts at most MAX_COUNT rows, so a large table never pays for a full COUNT(*).

    Pages past the cap are not reachable. Use the admin filters or search to reach older rows.
    """

    MAX_COUNT = 10_000

    @cached_property
    def count(self) -> int:
        return self.object_list[: self.MAX_COUNT].count()
