from collections.abc import Callable
from typing import TYPE_CHECKING

from posthog.hogql.database import lazy_join_tags as tags
from posthog.hogql.database.schema.account_aggregates import (
    account_custom_properties_join,
    account_notebooks_join,
    account_tags_join,
)
from posthog.hogql.database.schema.error_tracking_fingerprint_issue_state import (
    join_with_error_tracking_fingerprint_issue_state_table,
)
from posthog.hogql.database.schema.error_tracking_issue_fingerprint_overrides import (
    join_with_error_tracking_issue_fingerprint_overrides_table,
)
from posthog.hogql.database.schema.groups import join_with_group_n_table
from posthog.hogql.database.schema.groups_revenue_analytics import join_with_groups_revenue_analytics_table
from posthog.hogql.database.schema.person_distinct_id_overrides import join_with_person_distinct_id_overrides_table
from posthog.hogql.database.schema.person_distinct_ids import join_with_person_distinct_ids_table
from posthog.hogql.database.schema.persons import join_with_persons_table
from posthog.hogql.database.schema.persons_pdi import persons_pdi_join
from posthog.hogql.database.schema.persons_revenue_analytics import join_with_persons_revenue_analytics_table
from posthog.hogql.database.schema.session_replay_events import (
    join_replay_table_to_sessions_table_v1,
    join_replay_table_to_sessions_table_v2,
    join_replay_table_to_sessions_table_v3,
    join_with_console_logs_log_entries_table,
    join_with_events_table,
)
from posthog.hogql.database.schema.sessions_v1 import join_events_table_to_sessions_table
from posthog.hogql.database.schema.sessions_v2 import join_events_table_to_sessions_table_v2
from posthog.hogql.database.schema.sessions_v3 import join_events_table_to_sessions_table_v3
from posthog.hogql.database.warehouse_join_resolvers import (
    resolve_data_warehouse_experiments_join,
    resolve_data_warehouse_join,
    resolve_foreign_key_join,
)

if TYPE_CHECKING:
    from posthog.hogql import ast
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.models import LazyJoinToAdd

# A lazy-join resolver builds the JOIN ``ast.JoinExpr`` for a lazy join from plain data —
# the LazyJoin's ``from_field``/``to_field``/``resolver_params`` — plus the runtime
# resolution context and the query node. Resolvers are keyed by tag so a ``LazyJoin`` can
# describe its join declaratively (a tag + params) instead of carrying a Python closure,
# which is what makes a built ``Database`` serializable.
LazyJoinResolver = Callable[["LazyJoinToAdd", "HogQLContext", "ast.SelectQuery"], "ast.JoinExpr"]

# The explicit, closed list of every lazy-join resolver the engine supports. This is the
# contract a serialized Database depends on: a consumer (another process, a cache reader, a
# future non-Python engine) must implement exactly these tags. Add new resolvers here — a
# tag that isn't listed cannot be resolved.
RESOLVERS: dict[str, LazyJoinResolver] = {
    tags.FOREIGN_KEY: resolve_foreign_key_join,
    tags.DATA_WAREHOUSE: resolve_data_warehouse_join,
    tags.DATA_WAREHOUSE_EXPERIMENTS: resolve_data_warehouse_experiments_join,
    tags.PERSONS: join_with_persons_table,
    tags.PERSONS_PDI: persons_pdi_join,
    tags.PERSON_DISTINCT_IDS: join_with_person_distinct_ids_table,
    tags.PERSON_DISTINCT_ID_OVERRIDES: join_with_person_distinct_id_overrides_table,
    tags.GROUP_N: join_with_group_n_table,
    tags.GROUPS_REVENUE_ANALYTICS: join_with_groups_revenue_analytics_table,
    tags.PERSONS_REVENUE_ANALYTICS: join_with_persons_revenue_analytics_table,
    tags.EVENTS_TO_SESSIONS_V1: join_events_table_to_sessions_table,
    tags.EVENTS_TO_SESSIONS_V2: join_events_table_to_sessions_table_v2,
    tags.EVENTS_TO_SESSIONS_V3: join_events_table_to_sessions_table_v3,
    tags.REPLAY_TO_SESSIONS_V1: join_replay_table_to_sessions_table_v1,
    tags.REPLAY_TO_SESSIONS_V2: join_replay_table_to_sessions_table_v2,
    tags.REPLAY_TO_SESSIONS_V3: join_replay_table_to_sessions_table_v3,
    tags.REPLAY_TO_EVENTS: join_with_events_table,
    tags.REPLAY_TO_CONSOLE_LOGS: join_with_console_logs_log_entries_table,
    tags.ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES: join_with_error_tracking_issue_fingerprint_overrides_table,
    tags.ERROR_TRACKING_FINGERPRINT_ISSUE_STATE: join_with_error_tracking_fingerprint_issue_state_table,
    tags.ACCOUNT_TAGS: account_tags_join,
    tags.ACCOUNT_NOTEBOOKS: account_notebooks_join,
    tags.ACCOUNT_CUSTOM_PROPERTIES: account_custom_properties_join,
}


def get_lazy_join_resolver(name: str) -> LazyJoinResolver:
    try:
        return RESOLVERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown lazy join resolver {name!r}. Every supported resolver must be listed in RESOLVERS."
        ) from None
