from parameterized import parameterized

from products.data_warehouse.backend.direct_postgres import get_direct_postgres_location


class TestGetDirectPostgresLocation:
    @parameterized.expand(
        [
            ("whitespace_only_schema", "public.accounts", "   ", (None, "public", "accounts")),
            ("trimmed_schema", "accounts", " public ", (None, "public", "accounts")),
        ]
    )
    def test_normalizes_default_schema_before_inference(
        self, _name: str, schema_name: str, default_schema: str, expected: tuple[str | None, str, str]
    ) -> None:
        assert get_direct_postgres_location(schema_name=schema_name, default_schema=default_schema) == expected
