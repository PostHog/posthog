from posthog.schema import (
    AccountActivityMatrixColumn,
    AccountActivityMatrixEmptyReason,
    AccountAgentActivityBucket,
    AccountAgentActivityClient,
    AccountAgentActivityIntent,
    AccountAgentActivityQuery,
    AccountAgentActivityQueryResponse,
    AccountAgentActivityResult,
    AccountAgentActivityTool,
    AccountAgentActivityTotals,
    AccountAgentToolAccess,
    BookActivityMatrixProduct,
    CachedAccountAgentActivityQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from products.customer_analytics.backend.hogql_queries.account_scoped_activity_base import (
    AccountScopedActivityQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.book_activity_base import (
    agent_product_expr,
    day_key,
    effective_tool_expr,
)
from products.customer_analytics.backend.logic.agent_tool_access import classify_agent_tool_access
from products.customer_analytics.backend.logic.posthog_product_usage import AGENT_EVENT, POSTHOG_PRODUCTS

TOOL_LIMIT = 200
CLIENT_LIMIT = 10
INTENT_LIMIT = 20
INTENT_MAX_CHARS = 500
PAGEVIEW_EVENT = "$pageview"

CONVERSATION = "nullIf(toString(properties.$mcp_conversation_id), '')"
IS_ERROR = "toString(properties.$mcp_is_error) IN ('true', '1')"


class AccountAgentActivityQueryRunner(AccountScopedActivityQueryRunner[AccountAgentActivityQueryResponse]):
    """Runs 5 ClickHouse queries: the weekly trend, totals, tools, clients and intents."""

    query: AccountAgentActivityQuery
    cached_response: CachedAccountAgentActivityQueryResponse

    def to_query(self) -> ast.SelectQuery:
        external_id, group_type_index = self._group_identity()
        if not external_id or group_type_index is None:
            return ast.SelectQuery.empty()
        return self._tools_query(external_id, group_type_index)

    def _calculate(self) -> AccountAgentActivityQueryResponse:
        columns = self._columns()
        external_id, group_type_index = self._group_identity()
        if not external_id:
            return self._response(columns, empty_reason=AccountActivityMatrixEmptyReason.NO_EXTERNAL_ID)
        if group_type_index is None:
            return self._response(columns, empty_reason=AccountActivityMatrixEmptyReason.NO_GROUP_TYPE)

        buckets = self._buckets(external_id, group_type_index, columns)
        totals_row = self._run("AccountAgentActivityTotals", self._totals_query(external_id, group_type_index))
        agent_calls, agent_people, conversations, errors, ui_pageviews = (
            totals_row[0] if totals_row else (0, 0, 0, 0, 0)
        )
        tools = [
            AccountAgentActivityTool(
                product=str(product),
                tool=str(tool),
                access=AccountAgentToolAccess(classify_agent_tool_access(str(tool))),
                calls=int(calls),
                people=int(people),
                conversations=int(tool_conversations),
                errors=int(tool_errors),
            )
            for product, tool, calls, people, tool_conversations, tool_errors in self._run(
                "AccountAgentActivityTools", self._tools_query(external_id, group_type_index)
            )
        ]
        clients = [
            AccountAgentActivityClient(name=str(name), calls=int(calls), people=int(people))
            for name, calls, people in self._run(
                "AccountAgentActivityClients", self._clients_query(external_id, group_type_index)
            )
        ]
        intents = [
            AccountAgentActivityIntent(
                intent=str(intent),
                calls=int(calls),
                conversations=int(intent_conversations),
                lastSeen=last.isoformat() if hasattr(last, "isoformat") else str(last),
            )
            for intent, calls, intent_conversations, last in self._run(
                "AccountAgentActivityIntents", self._intents_query(external_id, group_type_index)
            )
        ]
        totals = AccountAgentActivityTotals(
            agentCalls=int(agent_calls),
            agentPeople=int(agent_people),
            conversations=int(conversations),
            errors=int(errors),
            reads=sum(tool.calls for tool in tools if tool.access == AccountAgentToolAccess.READ),
            writes=sum(tool.calls for tool in tools if tool.access == AccountAgentToolAccess.WRITE),
            uiPageviews=int(ui_pageviews),
        )
        return self._response(
            columns,
            buckets=buckets,
            totals=totals,
            tools=tools,
            clients=clients,
            intents=intents,
            truncated=len(tools) >= TOOL_LIMIT or len(clients) >= CLIENT_LIMIT or len(intents) >= INTENT_LIMIT,
        )

    def _response(
        self,
        columns: list[AccountActivityMatrixColumn],
        *,
        buckets: list[AccountAgentActivityBucket] | None = None,
        totals: AccountAgentActivityTotals | None = None,
        tools: list[AccountAgentActivityTool] | None = None,
        clients: list[AccountAgentActivityClient] | None = None,
        intents: list[AccountAgentActivityIntent] | None = None,
        truncated: bool = False,
        empty_reason: AccountActivityMatrixEmptyReason | None = None,
    ) -> AccountAgentActivityQueryResponse:
        return AccountAgentActivityQueryResponse(
            results=AccountAgentActivityResult(
                columns=columns,
                buckets=buckets
                if buckets is not None
                else [AccountAgentActivityBucket(column=column.key, agentCalls=0, uiPageviews=0) for column in columns],
                totals=totals
                or AccountAgentActivityTotals(
                    agentCalls=0, agentPeople=0, conversations=0, errors=0, reads=0, writes=0, uiPageviews=0
                ),
                products=[
                    BookActivityMatrixProduct(key=product.key, label=product.label) for product in POSTHOG_PRODUCTS
                ],
                tools=tools or [],
                clients=clients or [],
                intents=intents or [],
                truncated=truncated,
                emptyReason=empty_reason,
            ),
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _run(self, query_type: str, query: ast.SelectQuery) -> list:
        return list(self._execute(query_type, query).results or [])

    def _buckets(
        self, external_id: str, group_type_index: int, columns: list[AccountActivityMatrixColumn]
    ) -> list[AccountAgentActivityBucket]:
        query = self._select(
            """
            SELECT {week} AS week, countIf(event = {agent_event}) AS agent_calls,
                countIf(event = {pageview}) AS ui_pageviews
            FROM events WHERE {where}
            GROUP BY week
            """,
            external_id,
            group_type_index,
            [AGENT_EVENT, PAGEVIEW_EVENT],
            {"week": self._week_expr()},
        )
        counts = {
            day_key(week): (int(calls), int(pageviews))
            for week, calls, pageviews in self._run("AccountAgentActivityBuckets", query)
        }
        return [
            AccountAgentActivityBucket(
                column=column.key,
                agentCalls=counts.get(column.key, (0, 0))[0],
                uiPageviews=counts.get(column.key, (0, 0))[1],
            )
            for column in columns
        ]

    def _totals_query(self, external_id: str, group_type_index: int) -> ast.SelectQuery:
        return self._select(
            f"""
            SELECT countIf(event = {{agent_event}}), uniqIf(person_id, event = {{agent_event}}),
                uniqIf({CONVERSATION}, event = {{agent_event}}), countIf(event = {{agent_event}} AND {IS_ERROR}),
                countIf(event = {{pageview}})
            FROM events WHERE {{where}}
            """,
            external_id,
            group_type_index,
            [AGENT_EVENT, PAGEVIEW_EVENT],
        )

    def _tools_query(self, external_id: str, group_type_index: int) -> ast.SelectQuery:
        return self._select(
            f"""
            SELECT {{product}} AS product, {{tool}} AS tool, count() AS calls, uniq(person_id) AS people,
                uniq({CONVERSATION}) AS conversations, countIf({IS_ERROR}) AS errors
            FROM events WHERE {{where}}
            GROUP BY product, tool
            ORDER BY calls DESC, tool ASC
            LIMIT {TOOL_LIMIT}
            """,
            external_id,
            group_type_index,
            [AGENT_EVENT],
            {"product": agent_product_expr(), "tool": effective_tool_expr()},
        )

    def _clients_query(self, external_id: str, group_type_index: int) -> ast.SelectQuery:
        return self._select(
            f"""
            SELECT coalesce(nullIf(toString(properties.$mcp_client_name), ''), 'Unknown client') AS name,
                count() AS calls, uniq(person_id) AS people
            FROM events WHERE {{where}}
            GROUP BY name
            ORDER BY calls DESC, name ASC
            LIMIT {CLIENT_LIMIT}
            """,
            external_id,
            group_type_index,
            [AGENT_EVENT],
        )

    def _intents_query(self, external_id: str, group_type_index: int) -> ast.SelectQuery:
        return self._select(
            f"""
            SELECT substring(trim(toString(properties.$mcp_intent)), 1, {INTENT_MAX_CHARS}) AS intent, count() AS calls,
                uniq({CONVERSATION}) AS conversations, max(timestamp) AS last_seen
            FROM events WHERE {{where}} AND notEmpty(trim(coalesce(toString(properties.$mcp_intent), '')))
            GROUP BY intent
            ORDER BY calls DESC, last_seen DESC
            LIMIT {INTENT_LIMIT}
            """,
            external_id,
            group_type_index,
            [AGENT_EVENT],
        )

    def _select(
        self,
        query: str,
        external_id: str,
        group_type_index: int,
        events: list[str],
        extra: dict[str, ast.Expr] | None = None,
    ) -> ast.SelectQuery:
        select = parse_select(
            query,
            placeholders={
                "where": self._where(external_id, group_type_index, events),
                "agent_event": ast.Constant(value=AGENT_EVENT),
                "pageview": ast.Constant(value=PAGEVIEW_EVENT),
                **(extra or {}),
            },
        )
        assert isinstance(select, ast.SelectQuery)
        return select
