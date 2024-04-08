from posthog.test.base import BaseTest
from posthog.hogql.functions.mapping import find_clickhouse_function, HogQLFunctionMeta


class TestMappings(BaseTest):
    def _get_clickhouse_function(self, name: str) -> HogQLFunctionMeta:
        result = find_clickhouse_function(name)
        assert result is not None
        return result

    def test_find_case_sensitive_function(self):
        self.assertEquals(self._get_clickhouse_function("toString").clickhouse_name, "toString")
        self.assertEquals(find_clickhouse_function("TOString"), None)
        self.assertEquals(find_clickhouse_function("PlUs"), None)

    def test_find_case_insensitive_function(self):
        self.assertEquals(self._get_clickhouse_function("coalesce").clickhouse_name, "coalesce")
        self.assertEquals(self._get_clickhouse_function("CoAlesce").clickhouse_name, "coalesce")

    def test_find_non_existent_function(self):
        self.assertEquals(find_clickhouse_function("functionThatDoesntExist"), None)
