from functools import cached_property
from django.core.paginator import Paginator


class NoCountPaginator(Paginator):
    @cached_property
    def count(self):
        return 999999
