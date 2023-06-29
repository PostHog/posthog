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
                "errors": [{"message": "extraneous input '1' expecting <EOF>", "start": 7, "end": 8, "fix": None}],
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
                "errors": [],
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
                "errors": [],
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
                "errors": [
                    {
                        "message": "mismatched input 'timestamp' expecting {SELECT, WITH, '('}",
                        "start": 0,
                        "end": 9,
                        "fix": None,
                    }
                ],
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
                "errors": [
                    {
                        "message": "Alias 'true' is a reserved keyword.",
                        "start": 0,
                        "end": 9,
                        "fix": None,
                    }
                ],
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
                "errors": [
                    {
                        "message": "Unable to resolve field: no_field",
                        "start": 4,
                        "end": 12,
                        "fix": None,
                    }
                ],
            },
        )
