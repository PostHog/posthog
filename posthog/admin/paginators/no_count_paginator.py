from django.core.paginator import Paginator


class NoCountPaginator(Paginator):
    @property
    def count(self):
        return 999999
