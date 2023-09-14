from .runner import QueryRunner
from .mixins import FilterTestAccountsMixin


class LifecycleQueryRunner(FilterTestAccountsMixin, QueryRunner):
    pass
