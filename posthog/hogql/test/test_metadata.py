from posthog.hogql.metadata import get_hogql_metadata
from posthog.schema import HogQLMetadata, HogQLMetadataResponse
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestMetadata(ClickhouseTestMixin, APIBaseTest):
    def _expr(self, query: str) -> HogQLMetadataResponse:
        return get_hogql_metadata(query=HogQLMetadata(expr=query), team=self.team)

    def _select(self, query: str) -> HogQLMetadataResponse:
        return get_hogql_metadata(query=HogQLMetadata(select=query), team=self.team)

    def test_metadata_valid_expr_select(self):
        metadata = self._expr("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "expr": "select 1",
                "select": None,
                "error": "Syntax error at line 1, column 7: extraneous input '1' expecting <EOF>",
            },
        )

        metadata = self._select("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "expr": None,
                "select": "select 1",
                "error": None,
            },
        )

        metadata = self._expr("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "expr": "timestamp",
                "select": None,
                "error": None,
            },
        )

        metadata = self._select("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "expr": None,
                "select": "timestamp",
                "error": "Syntax error at line 1, column 0: mismatched input 'timestamp' expecting {SELECT, WITH, '('}",
            },
        )
