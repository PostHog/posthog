from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import (
    DateRange,
    DistanceFunc,
    DocumentSimilarityQuery,
    DocumentSimilarityQueryResponse,
    EmbeddedDocument,
    OrderBy,
    OrderDirection,
)

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.document_embeddings_query_runner import DocumentEmbeddingsQueryRunner


def build_document_similarity_query(
    origin: EmbeddedDocument,
    model: str,
    products: list[str] | None = None,
    document_types: list[str] | None = None,
    renderings: list[str] | None = None,
    distance_func: DistanceFunc = DistanceFunc.COSINE_DISTANCE,
    order_by: OrderBy = OrderBy.DISTANCE,
    order_direction: OrderDirection = OrderDirection.ASC,
    limit: int | None = None,
    offset: int | None = None,
) -> DocumentSimilarityQuery:
    date_from = (origin.timestamp - timedelta(days=1)).date().isoformat()
    date_to = (origin.timestamp + timedelta(days=1)).date().isoformat()

    return DocumentSimilarityQuery(
        kind="DocumentSimilarityQuery",
        model=model,
        distance_func=distance_func,
        order_by=order_by,
        order_direction=order_direction,
        dateRange=DateRange(date_from=date_from, date_to=date_to),
        origin=origin,
        products=products or [],
        document_types=document_types or [],
        renderings=renderings or [],
        limit=limit,
        offset=offset,
        threshold=None,
    )


class TestDocumentEmbeddingsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    base_timestamp = datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    product_documents = (
        ("product_a", "document_a", "doc_product_a"),
        ("product_b", "document_b", "doc_product_b"),
    )
    renderings = ("text", "html")
    models = {
        "text-embedding-3-small-1536": 3,
        "text-embedding-3-large-3072": 5,
    }

    def setUp(self):
        super().setUp()
        self.embedding_rows = self._seed_document_embeddings()

    @dataclass(frozen=True)
    class DocumentEmbeddingRow:
        document: EmbeddedDocument
        rendering: str
        model_name: str
        embedding: tuple[float, ...]
        inserted_at: datetime

    def _seed_document_embeddings(self) -> list[DocumentEmbeddingRow]:
        sync_execute("TRUNCATE TABLE posthog_document_embeddings", flush=False, team_id=self.team.pk)

        fixtures: list[TestDocumentEmbeddingsQueryRunner.DocumentEmbeddingRow] = []
        rows: list[tuple] = []
        row_index = 0

        for product, document_type, document_id in self.product_documents:
            for rendering in self.renderings:
                for model_name, dimension in self.models.items():
                    timestamp = self.base_timestamp + timedelta(minutes=row_index)
                    inserted_at = timestamp + timedelta(seconds=dimension)
                    embedding = tuple(float(row_index + i) for i in range(dimension))
                    embedded_document = EmbeddedDocument(
                        product=product,
                        document_type=document_type,
                        document_id=document_id,
                        timestamp=timestamp,
                    )

                    rows.append(
                        (
                            self.team.pk,
                            product,
                            document_type,
                            model_name,
                            rendering,
                            document_id,
                            timestamp,
                            inserted_at,
                            list(embedding),
                            inserted_at,
                            row_index,
                            0,
                        )
                    )

                    fixtures.append(
                        TestDocumentEmbeddingsQueryRunner.DocumentEmbeddingRow(
                            document=embedded_document,
                            rendering=rendering,
                            model_name=model_name,
                            embedding=embedding,
                            inserted_at=inserted_at,
                        )
                    )

                    row_index += 1

        if rows:
            sync_execute(
                """
                INSERT INTO posthog_document_embeddings (
                    team_id,
                    product,
                    document_type,
                    model_name,
                    rendering,
                    document_id,
                    timestamp,
                    inserted_at,
                    embedding,
                    _timestamp,
                    _offset,
                    _partition
                ) VALUES
                """,
                rows,
                flush=False,
                team_id=self.team.pk,
            )

        return fixtures

    def test_query_basic(self):
        origin_row = self.embedding_rows[0]
        origin_document = origin_row.document

        query = build_document_similarity_query(
            origin=origin_document,
            model=origin_row.model_name,
            products=[],
            document_types=[],
        )

        response = DocumentEmbeddingsQueryRunner(team=self.team, query=query).calculate()

        # The runner returns the best match for each unique (product, document_type, document_id),
        # which in this case means itself, and the only other document.
        self.assertEqual(len(response.results), 2)

        first_result = response.results[0].result
        self.assertEqual(first_result.product, origin_document.product)
        self.assertEqual(first_result.document_type, origin_document.document_type)
        self.assertEqual(first_result.document_id, origin_document.document_id)
        self.assertEqual(first_result.model_name, origin_row.model_name)
        # Commented out for the sake of being explicit - without specifying a set of possible
        # renderings in the query runner, the runner will return the nearest rendering type within
        # the range of available renderings, for a (product, document_type) universe of renderings
        # self.assertEqual(first_result.rendering, origin_row["rendering"])

        # The second document is the one with the opposite (product, document_type, document_id)
        # We again can't assert on rendering, but can assert on model_name
        second_result = response.results[1].result
        self.assertNotEqual(second_result.product, origin_document.product)
        self.assertNotEqual(second_result.document_type, origin_document.document_type)
        self.assertNotEqual(second_result.document_id, origin_document.document_id)
        self.assertEqual(second_result.model_name, origin_row.model_name)

    def test_query_respects_product_filter(self):
        # IMPORTANT - we do not filter the origin select, only the returned results - so we re-use
        # the same row across queries for both products, and get 1 result both times. This is because
        # we want to support users saying stuff like "give me the most similar documents from product_b
        # to this document from product_a", and that should only return documents from product_b.
        origin_row = next(row for row in self.embedding_rows if row.document.product == "product_a")
        origin_document = origin_row.document

        query_product_b = build_document_similarity_query(
            origin=origin_document,
            model=origin_row.model_name,
            products=["product_b"],
        )
        response = DocumentEmbeddingsQueryRunner(team=self.team, query=query_product_b).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].result.product, "product_b")

        query_product_a = build_document_similarity_query(
            origin=origin_document,
            model=origin_row.model_name,
            products=["product_a"],
        )
        response = DocumentEmbeddingsQueryRunner(team=self.team, query=query_product_a).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].result.product, "product_a")

    def test_query_respects_rendering_filter(self):
        # As above, but for renderings rather than products - we support filtering by rendering type.
        # Notably, we don't let callers specify the rendering to use for the origin. This is because
        # we only compare like-for-like renderings within a (product, document_type) group, and want
        # to ensure we include all relevant documents. The != in this selection is meant
        # to demonstrate this - the origin selection DOES NOT specify a rendering type, rendering
        # filters (and product, and document type) are exclusively applied to the universe the
        # origin is compared against
        origin_row = next(row for row in self.embedding_rows if row.rendering != "text")
        origin_document = origin_row.document

        query = build_document_similarity_query(
            origin=origin_document,
            model=origin_row.model_name,
            renderings=["text"],
        )

        response = DocumentEmbeddingsQueryRunner(team=self.team, query=query).calculate()
        self.assertEqual(len(response.results), 2)
        for result in response.results:
            self.assertEqual(result.result.rendering, "text")

    def test_descending_order_places_other_product_first(self):
        origin_row = self.embedding_rows[0]
        origin_document = origin_row.document

        query = build_document_similarity_query(
            origin=origin_document,
            model=origin_row.model_name,
            order_direction=OrderDirection.DESC,
        )

        response = DocumentEmbeddingsQueryRunner(team=self.team, query=query).calculate()
        self.assertIsInstance(response, DocumentSimilarityQueryResponse)
        self.assertGreaterEqual(len(response.results), 1)
        top_result = response.results[0].result
        self.assertFalse(
            top_result.product == origin_document.product
            and top_result.document_type == origin_document.document_type
            and top_result.document_id == origin_document.document_id
        )
