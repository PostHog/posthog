import re

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin, TaxonomyFiltersMixin
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.schema import (
    CachedPropertyValueSearchQueryResponse,
    PropertyValueSearchEntityKind,
    PropertyValueSearchItem,
    PropertyValueSearchQuery,
    PropertyValueSearchQueryResponse,
)


class PropertyValueSearchQueryRunner(TaxonomyCacheMixin, TaxonomyFiltersMixin, AnalyticsQueryRunner):
    query: PropertyValueSearchQuery
    response: PropertyValueSearchQueryResponse
    cached_response: CachedPropertyValueSearchQueryResponse

    def _calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="PropertyValueSearchQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results: list[PropertyValueSearchItem] = []
        for row in response.results:
            results.append(PropertyValueSearchItem(property=row[0], value=row[1], score=row[-1]))

        return PropertyValueSearchQueryResponse(
            results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        query = parse_select(
            """
                SELECT
                    prop.1 AS property_key,
                    prop.2 AS property_value,
                    {token_matches} AS token_hits,
                    (token_hits = {token_count}) AS all_tokens,
                    positionCaseInsensitiveUTF8(property_value, {search_query}) AS phrase_pos,
                    ngramSearchCaseInsensitiveUTF8(property_value, {search_query}) AS ngram_sim,
                    startsWith(property_value, {search_query}) OR startsWith(lowerUTF8(property_value), {search_query}) AS is_prefix,
                    (all_tokens * 5)
                     + (if(phrase_pos > 0, 3, 0))
                     + (is_prefix * 2)
                     + (ngram_sim * 1.5)
                     + (if(phrase_pos > 0, 1 / least(phrase_pos, 200), 0)) AS score
                FROM {subquery}
                ORDER BY score DESC
                LIMIT 100
            """,
            placeholders={
                "token_matches": self._get_tokenizer_expr(),
                "token_count": ast.Constant(value=len(self._tokenize_query())),
                "search_query": ast.Constant(value=self.query.searchQuery),
                "subquery": self._get_subquery(),
            },
        )
        return query

    def _tokenize_query(self) -> list[str]:
        text = self.query.searchQuery.casefold()
        return re.findall(r"[^\W_]+", text)

    def _get_tokenizer_expr(self):
        tokens = self._tokenize_query()
        return parse_expr(
            " + ".join(f"ifNull(hasTokenCaseInsensitive(property_value, '{token}'), 0)" for token in tokens)
        )

    def _get_subquery(self):
        if self.query.entityKind == PropertyValueSearchEntityKind.EVENT:
            return self._get_events_query()
        raise NotImplementedError(f"Filter query for entity kind {self.query.entityKind} is not implemented")

    def _get_events_query(self):
        if not self.query.properties:
            json_projection = parse_expr("JSONExtractKeysAndValues(properties, 'String')")
        else:
            json_projection = ast.Array(
                exprs=[
                    ast.Tuple(exprs=[ast.Constant(value=prop), ast.Field(chain=["properties", prop])])
                    for prop in self.query.properties
                ]
            )

        if self.query.events:
            event_filter = parse_expr(
                "event IN ({events})",
                placeholders={"events": ast.Array(exprs=[ast.Constant(value=event) for event in self.query.events])},
            )
        else:
            event_filter = parse_expr("1")

        # TODO: add smaller windows for high-volume orgs
        # TODO: add a filter for excluded meaningless property values and events
        return parse_select(
            """
                SELECT
                    DISTINCT kv as prop
                FROM
                    events
                ARRAY JOIN
                    {projection} AS kv
                WHERE
                    {event_filter}
                    AND {event_omit_filter}
                    AND timestamp >= today() - INTERVAL {day_count} DAY
                    AND kv.1 IS NOT NULL
                    AND kv.2 IS NOT NULL
                    AND NOT match(kv.1, {property_omit_filter})
            """,
            placeholders={
                "event_filter": event_filter,
                "event_omit_filter": self._get_ignored_system_events_expr(),
                "property_omit_filter": self._get_ignored_properties_regex_expr(),
                "projection": json_projection,
                "day_count": ast.Constant(value=30),
            },
        )
