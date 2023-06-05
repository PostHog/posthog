from posthog.hogql.metadata import get_hogql_metadata
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestMetadata(ClickhouseTestMixin, APIBaseTest):
    def test_netadata_valid_expr_select(self):
        metadata = get_hogql_metadata(expr="select 1")
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

        metadata = get_hogql_metadata(select="select 1")
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

        metadata = get_hogql_metadata(expr="timestamp")
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

        metadata = get_hogql_metadata(select="timestamp")
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
