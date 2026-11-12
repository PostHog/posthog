"""Facade re-exports for customer_analytics query runners.

Core's query-runner registry (``posthog/hogql_queries/query_runner.py``) dispatches
on query ``kind`` and constructs these runners by class identity. Re-exporting the
classes keeps that registry coupling at the facade boundary while query implementation
imports stay out of ``facade/api.py`` so config-only consumers don't drag them onto
the ``django.setup()`` path.
"""

from products.customer_analytics.backend.hogql_queries.account_activity_matrix_query_runner import (
    AccountActivityMatrixQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.account_users_query_runner import AccountUsersQueryRunner
from products.customer_analytics.backend.hogql_queries.accounts_query_runner import AccountsQueryRunner
from products.customer_analytics.backend.hogql_queries.accounts_table_query_runner import AccountsTableQueryRunner
from products.customer_analytics.backend.hogql_queries.book_activity_firsts_query_runner import (
    BookActivityFirstsQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.book_activity_matrix_query_runner import (
    BookActivityMatrixQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.book_activity_people_query_runner import (
    BookActivityPeopleQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.usage_metrics_query_runner import UsageMetricsQueryRunner

__all__ = [
    "AccountActivityMatrixQueryRunner",
    "AccountUsersQueryRunner",
    "AccountsQueryRunner",
    "AccountsTableQueryRunner",
    "BookActivityFirstsQueryRunner",
    "BookActivityMatrixQueryRunner",
    "BookActivityPeopleQueryRunner",
    "UsageMetricsQueryRunner",
]
