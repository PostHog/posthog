import datetime
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedDocumentEmbeddingsQueryResponse,
    DateRange,
    DistanceFunc,
    DocumentEmbeddingsQuery,
    DocumentEmbeddingsQueryResponse,
    EmbeddedDocument,
    EmbeddedDocumentQuery,
    EmbeddingDistance,
    EmbeddingModelName,
    EmbeddingRecord,
    OrderBy,
    OrderDirection,
    Specificity,
)

from posthog.hogql import ast

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.tasks.tasks import LimitContext
from posthog.utils import relative_date_parse


# The metaphor here is broken - a needle is a thing you search for, not a thing you
# search with, but I've used it here to me "the input query embedding", and used
# "haystack" to mean the returned documents being distance matched. I do like the image
# of a man going through a haystack with a needle, searching for something piece by piece,
# though.
class DocumentEmbeddingsQueryRunner(AnalyticsQueryRunner[DocumentEmbeddingsQueryResponse]):
    query: DocumentEmbeddingsQuery
    cached_response: CachedDocumentEmbeddingsQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime
    needle: EmbeddedDocumentQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )
        self.date_from = DocumentEmbeddingsQueryRunner.parse_relative_date_from(self.query.dateRange.date_from)
        self.date_to = DocumentEmbeddingsQueryRunner.parse_relative_date_to(self.query.dateRange.date_to)
        self.needle = self.query.needle

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

    def _calculate(self) -> DocumentEmbeddingsQueryResponse:
        with self.timings.measure("document_embeddings_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="DocumentEmbeddingsQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        columns: list[str] = query_result.columns or []
        mapped_result = [dict(zip(columns, value)) for value in query_result]
        results = [
            EmbeddingDistance(  # noqa: F821
                distance=row["distance"],
                result=EmbeddingRecord(
                    product=row["haystack_product"],
                    document_type=row["haystack_document_type"],
                    document_id=row["haystack_document_id"],
                    timestamp=row["haystack_timestamp"],
                    model_name=row["haystack_model_name"],
                    rendering=row["haystack_rendering"],
                ),
                query=None,
            )
            for row in mapped_result
        ]

        return DocumentEmbeddingsQueryResponse(
            columns=columns,
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def to_query(self) -> ast.SelectQuery:
        haystack = lambda col: column("haystack", col)
        needle = lambda col: column("needle", col)

        nearest = lambda expr: ast.Call(
            name=self.output_argby_func,
            args=[expr, self.distance_expr(haystack("embedding"), needle("embedding"))],
        )

        cols = [
            ast.Alias(alias="haystack_product", expr=haystack("product")),
            ast.Alias(alias="haystack_document_type", expr=haystack("document_type")),
            ast.Alias(alias="haystack_model_name", expr=nearest(haystack("model_name"))),
            ast.Alias(alias="haystack_rendering", expr=nearest(haystack("rendering"))),
            ast.Alias(alias="haystack_document_id", expr=haystack("document_id")),
            ast.Alias(alias="haystack_timestamp", expr=haystack("timestamp")),
            ast.Alias(alias="needle_product", expr=nearest(needle("product"))),
            ast.Alias(alias="needle_document_type", expr=nearest(needle("document_type"))),
            ast.Alias(alias="needle_model_name", expr=nearest(needle("model_name"))),
            ast.Alias(alias="needle_rendering", expr=nearest(needle("rendering"))),
            ast.Alias(alias="needle_document_id", expr=nearest(needle("document_id"))),
            ast.Alias(alias="needle_timestamp", expr=nearest(needle("timestamp"))),
            ast.Alias(
                alias="distance",
                expr=ast.Call(
                    name=self.output_distance_agg, args=[self.distance_expr(haystack("embedding"), needle("embedding"))]
                ),
            ),
        ]

        group_by = [
            haystack("product"),
            haystack("document_type"),
            haystack("document_id"),
            haystack("timestamp"),
        ]

        where_exprs = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=ast.Constant(value=self.date_from), right=haystack("timestamp")
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq, left=ast.Constant(value=self.date_to), right=haystack("timestamp")
            ),
            # TODO - right now "specificity" is how people control what documents to compare the
            # query document to. This basically sucks - we should expose "product", "document_type" and
            # maybe "rendering" as taxonomic filter properties and let people write arbitrary queries
            # against them. We should also expose the ID of the document (in case it's semantically useful)
            # We should expose timestamp and distance too, so they can ve used in where clauses and order by's at
            # will
        ]

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
                        left=ast.Field(chain=["needle", "model_name"]),
                        right=ast.Field(chain=["haystack", "model_name"]),
                    ),
                    ast.Or(
                        exprs=[
                            ast.And(
                                exprs=[
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["needle", "product"]),
                                        right=ast.Field(chain=["haystack", "product"]),
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["needle", "document_type"]),
                                        right=ast.Field(chain=["haystack", "document_type"]),
                                    ),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["needle", "rendering"]),
                                        right=ast.Field(chain=["haystack", "rendering"]),
                                    ),
                                ]
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.NotEq,
                                left=ast.Field(chain=["needle", "document_type"]),
                                right=ast.Field(chain=["haystack", "document_type"]),
                            ),
                        ]
                    ),
                ],
            ),
        )

        return ast.JoinExpr(
            table=self.needle_select,
            alias="needle",
            next_join=ast.JoinExpr(
                join_type="INNER JOIN",
                constraint=constraint,
                table=ast.Field(chain=["posthog_document_embeddings"]),
                alias="haystack",
            ),
        )

    @property
    def needle_select(self) -> ast.SelectQuery:
        # We're argMax'ing columns to output cols of the same name, so we do this. I think
        # the hogql parser would actually handle this for us, but I'm doing it here for clarity,
        # and because it made local work faster to test
        col = lambda col: column("d", col)
        # We do this because we fuzzy match on timestamp, and people might mess up
        most_recent = lambda expr: ast.Call(
            name="argMax",
            args=[expr, col("timestamp")],
        )
        select_cols = [
            ast.Alias(alias="product", expr=most_recent(col("product"))),
            ast.Alias(alias="document_type", expr=most_recent(col("document_type"))),
            ast.Alias(alias="document_id", expr=most_recent(col("document_id"))),
            ast.Alias(alias="timestamp", expr=most_recent(col("timestamp"))),
            ast.Alias(alias="model_name", expr=most_recent(col("model_name"))),
            ast.Alias(alias="rendering", expr=most_recent(col("rendering"))),
            ast.Alias(alias="embedding", expr=most_recent(col("embedding"))),
        ]

        where_exprs = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("product"),
                right=ast.Constant(value=self.needle.needle.product),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("document_type"),
                right=ast.Constant(value=self.needle.needle.document_type),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("document_id"),
                right=ast.Constant(value=self.needle.needle.document_id),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=col("model_name"),
                right=ast.Constant(value=str(self.needle.model_name)),
            ),
            timestamp_fuzzy_match(col("timestamp"), self.needle.needle.timestamp, datetime.timedelta(hours=1)),
        ]

        # If we're searching across products, you have to tell use which rendering to
        # use for the needle embedding
        # TODO - this is a hack, see comment in where exprs of output select
        if self.needle.specificity in ["any", "product"]:
            if self.needle.rendering is None:
                raise ValueError(f"{self.needle.specificity} rendering requires a rendering value")
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=col("rendering"),
                    right=ast.Constant(value=self.needle.rendering),
                )
            )

        group_by = [
            col("product"),
            col("document_type"),
            col("document_id"),
            col("model_name"),
            col("rendering"),
        ]

        return ast.SelectQuery(
            select=select_cols,
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog_document_embeddings"]), alias="d"),
            group_by=group_by,
            where=ast.And(exprs=where_exprs),
        )

    @property
    def order_by(self):
        order_direction = "ASC" if self.query.order_direction == "asc" else "DESC"
        if self.query.order_by == "distance":
            return [ast.OrderExpr(expr=ast.Field(chain=["distance"]), order=order_direction)]
        elif self.query.order_by == "timestamp":
            return [ast.OrderExpr(expr=ast.Field(chain=["haystack_timestamp"]), order=order_direction)]

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


def get_embedding_test_doc():
    return DocumentEmbeddingsQuery(
        needle=EmbeddedDocumentQuery(
            needle=EmbeddedDocument(
                product="docs",
                document_type="api",
                document_id="1234",
                timestamp=datetime.datetime.now() - datetime.timedelta(days=1),
            ),
            model_name=EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536,
            rendering="text",
            specificity=Specificity.DOCUMENT_TYPE,
        ),
        dateRange=DateRange(),
        distance_func=DistanceFunc.COSINE_DISTANCE,
        order_by=OrderBy.DISTANCE,
        order_direction=OrderDirection.ASC,
        limit=10,
        offset=0,
        threshold=0.5,
    )


def column(*chain: str):
    return ast.Field(chain=list(chain))
