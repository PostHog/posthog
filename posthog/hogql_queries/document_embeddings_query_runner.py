import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedDocumentSimilarityQueryResponse,
    DocumentSimilarityQuery,
    DocumentSimilarityQueryResponse,
    EmbeddedDocument,
    EmbeddingDistance,
    EmbeddingRecord,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.utils import relative_date_parse


class DocumentEmbeddingsQueryRunner(AnalyticsQueryRunner[DocumentSimilarityQueryResponse]):
    query: DocumentSimilarityQuery
    cached_response: CachedDocumentSimilarityQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime
    origin: EmbeddedDocument

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )
        self.date_from = DocumentEmbeddingsQueryRunner.parse_relative_date_from(self.query.dateRange.date_from)
        self.date_to = DocumentEmbeddingsQueryRunner.parse_relative_date_to(self.query.dateRange.date_to)
        self.origin = self.query.origin

    @classmethod
    def parse_relative_date_from(cls, date: str | None) -> datetime.datetime:
        if date == "all" or date is None:
            return datetime.datetime.now(tz=ZoneInfo("UTC")) - datetime.timedelta(days=365 * 4)  # 4 years ago

        return relative_date_parse(date, now=datetime.datetime.now(tz=ZoneInfo("UTC")), timezone_info=ZoneInfo("UTC"))

    @classmethod
    def parse_relative_date_to(cls, date: str | None) -> datetime.datetime:
        if not date:
            return datetime.datetime.now(tz=ZoneInfo("UTC"))
        if date == "all":
            raise ValueError("Invalid date range")

        return relative_date_parse(date, ZoneInfo("UTC"), increase=True)

    def _calculate(self) -> DocumentSimilarityQueryResponse:
        with self.timings.measure("document_embeddings_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="DocumentSimilarityQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        columns: list[str] = query_result.columns or []
        mapped_result = [dict(zip(columns, value)) for value in query_result.results]
        results = [
            EmbeddingDistance(  # noqa: F821
                distance=row["distance"],
                result=EmbeddingRecord(
                    product=row["result_product"],
                    document_type=row["result_document_type"],
                    document_id=row["result_document_id"],
                    timestamp=row["result_timestamp"],
                    model_name=row["result_model_name"],
                    rendering=row["result_rendering"],
                ),
                origin=None,
            )
            for row in mapped_result
        ]

        return DocumentSimilarityQueryResponse(
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def to_query(self) -> ast.SelectQuery:
        # as in "universal set"
        universe = lambda col: column("universe", col)
        # as in "point from which all distances are measured"
        origin = lambda col: column("origin", col)

        nearest = lambda expr: ast.Call(
            name=self.output_argby_func,
            args=[expr, self.distance_expr(universe("embedding"), origin("embedding"))],
        )

        cols: list[ast.Expr] = [
            ast.Alias(alias="result_product", expr=universe("product")),
            ast.Alias(alias="result_document_type", expr=universe("document_type")),
            ast.Alias(alias="result_model_name", expr=nearest(universe("model_name"))),
            ast.Alias(alias="result_rendering", expr=nearest(universe("rendering"))),
            ast.Alias(alias="result_document_id", expr=universe("document_id")),
            ast.Alias(alias="result_timestamp", expr=universe("timestamp")),
            ast.Alias(alias="origin_product", expr=nearest(origin("product"))),
            ast.Alias(alias="origin_document_type", expr=nearest(origin("document_type"))),
            ast.Alias(alias="origin_model_name", expr=nearest(origin("model_name"))),
            ast.Alias(alias="origin_rendering", expr=nearest(origin("rendering"))),
            ast.Alias(alias="origin_document_id", expr=nearest(origin("document_id"))),
            ast.Alias(alias="origin_timestamp", expr=nearest(origin("timestamp"))),
            ast.Alias(
                alias="distance",
                expr=ast.Call(
                    name=self.output_distance_agg, args=[self.distance_expr(universe("embedding"), origin("embedding"))]
                ),
            ),
        ]

        group_by: list[ast.Expr] = [
            universe("product"),
            universe("document_type"),
            universe("document_id"),
            universe("timestamp"),
        ]

        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=universe("timestamp"), right=ast.Constant(value=self.date_from)
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq, left=universe("timestamp"), right=ast.Constant(value=self.date_to)
            ),
        ]

        if self.query.products:
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=universe("product"),
                    right=ast.Constant(value=self.query.products),
                )
            )

        if self.query.document_types:
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=universe("document_type"),
                    right=ast.Constant(value=self.query.document_types),
                )
            )

        if self.query.renderings:
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=universe("rendering"),
                    right=ast.Constant(value=self.query.renderings),
                )
            )

        return ast.SelectQuery(
            select=cols,
            select_from=self.join_expr,
            group_by=group_by,  # If we got multiple hits for a doc, we take the best one
            order_by=self.order_by,
            where=ast.And(exprs=where_exprs),
        )

    @property
    def join_expr(self) -> ast.JoinExpr:
        constraint = ast.JoinConstraint(
            constraint_type="ON",
            expr=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["origin", "model_name"]),
                        right=ast.Field(chain=["universe", "model_name"]),
                    ),
                    ast.Or(
                        exprs=[
                            ast.And(
                                exprs=[
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["origin", "product"]),
                                        right=ast.Field(chain=["universe", "product"]),
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["origin", "document_type"]),
                                        right=ast.Field(chain=["universe", "document_type"]),
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["origin", "rendering"]),
                                        right=ast.Field(chain=["universe", "rendering"]),
                                    ),
                                ]
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.NotEq,
                                left=ast.Field(chain=["origin", "document_type"]),
                                right=ast.Field(chain=["universe", "document_type"]),
                            ),
                        ]
                    ),
                ],
            ),
        )

        return ast.JoinExpr(
            table=self.origin_select,
            alias="origin",
            next_join=ast.JoinExpr(
                join_type="INNER JOIN",
                constraint=constraint,
                table=ast.Field(chain=["document_embeddings"]),
                alias="universe",
            ),
        )

    @property
    def origin_select(self) -> ast.SelectQuery:
        # We're argMax'ing columns to output cols of the same name, so we do this. I think
        # the hogql parser would actually handle this for us, but I'm doing it here for clarity,
        # and because it made local work faster to test
        col = lambda col: column("d", col)
        # We do this because we fuzzy match on timestamp, and people might mess up
        most_recent = lambda expr: ast.Call(
            name="argMax",
            args=[expr, col("timestamp")],
        )
        select_cols: list[ast.Expr] = [
            ast.Alias(alias="product", expr=most_recent(col("product"))),
            ast.Alias(alias="document_type", expr=most_recent(col("document_type"))),
            ast.Alias(alias="document_id", expr=most_recent(col("document_id"))),
            ast.Alias(alias="timestamp", expr=most_recent(col("timestamp"))),
            ast.Alias(alias="model_name", expr=most_recent(col("model_name"))),
            ast.Alias(alias="rendering", expr=most_recent(col("rendering"))),
            ast.Alias(alias="embedding", expr=most_recent(col("embedding"))),
        ]

        # Note that one thing node added here is renderings - even if the caller specified
        # a set of renderings to select for, we still use all available renderings for the
        # origin in the join, we simply exclude it from the result set. The renderings filter
        # is the same as the product and document type filters semantically for this query,
        # which is to say it's only applied to the final output
        where_exprs = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("product"),
                right=ast.Constant(value=self.origin.product),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("document_type"),
                right=ast.Constant(value=self.origin.document_type),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("document_id"),
                right=ast.Constant(value=self.origin.document_id),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("model_name"),
                right=ast.Constant(value=str(self.query.model)),
            ),
            timestamp_fuzzy_match(col("timestamp"), self.origin.timestamp, datetime.timedelta(hours=1)),
        ]

        group_by: list[ast.Expr] = [
            col("product"),
            col("document_type"),
            col("document_id"),
            col("model_name"),
            col("rendering"),
        ]

        return ast.SelectQuery(
            select=select_cols,
            select_from=ast.JoinExpr(table=ast.Field(chain=["document_embeddings"]), alias="d"),
            group_by=group_by,
            where=ast.And(exprs=where_exprs),
        )

    @property
    def order_by(self):
        order_direction: Literal["ASC", "DESC"] = "ASC" if self.query.order_direction == "asc" else "DESC"
        if self.query.order_by == "distance":
            return [ast.OrderExpr(expr=ast.Field(chain=["distance"]), order=order_direction)]
        elif self.query.order_by == "timestamp":
            return [ast.OrderExpr(expr=ast.Field(chain=["result_timestamp"]), order=order_direction)]

    @property
    def output_argby_func(self):
        # If we're ordering by timestamp, always return the nearest row for a given document
        if self.query.order_by == "timestamp":
            func = "argMin"
        else:
            func = "argMin" if self.query.order_direction == "asc" else "argMax"
        return func

    @property
    def output_distance_agg(self):
        # If we're ordering by timestamp, always return the nearest row for a given document
        if self.query.order_by == "timestamp":
            func = "min"
        else:
            func = "min" if self.query.order_direction == "asc" else "max"
        return func

    def distance_expr(self, left: ast.Field, right: ast.Field) -> ast.Expr:
        return ast.Call(name=self.query.distance_func, args=[left, right])


def timestamp_fuzzy_match(left: ast.Expr, timestamp: datetime.datetime, range: datetime.timedelta) -> ast.Expr:
    # Create a select expr that matches a timestamp +/- an hour
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=left,
                right=ast.Constant(value=timestamp - range),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=left,
                right=ast.Constant(value=timestamp + range),
            ),
        ]
    )


def column(*chain: str):
    return ast.Field(chain=list(chain))
