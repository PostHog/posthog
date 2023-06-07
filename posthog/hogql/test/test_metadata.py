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
                "inputExpr": "select 1",
                "inputSelect": None,
                "error": "Syntax error at line 1, column 7: extraneous input '1' expecting <EOF>",
            },
        )

        metadata = self._select("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "inputExpr": None,
                "inputSelect": "select 1",
                "error": None,
            },
        )

        metadata = self._expr("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "inputExpr": "timestamp",
                "inputSelect": None,
                "error": None,
            },
        )

        metadata = self._select("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "inputExpr": None,
                "inputSelect": "timestamp",
                "error": "Syntax error at line 1, column 0: mismatched input 'timestamp' expecting {SELECT, WITH, '('}",
                "errorStart": None,
                "errorEnd": None,
            },
        )

    def test_metadata_expr_parse_error(self):
        metadata = self._expr("1 as true")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "inputExpr": "1 as true",
                "inputSelect": None,
                "error": "Alias 'true' is a reserved keyword.",
                "errorStart": 0,
                "errorEnd": 9,
            },
        )

    def test_metadata_expr_resolve_error(self):
        metadata = self._expr("1 + no_field")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "inputExpr": "1 + no_field",
                "inputSelect": None,
                "error": "Unable to resolve field: no_field",
                "errorStart": 4,
                "errorEnd": 12,
            },
        )
