from posthog.schema import SourceFieldInputConfig

from posthog.temporal.data_imports.sources.supabase.source import SupabaseSource


def test_supabase_requires_schema_field():
    source_config = SupabaseSource().get_source_config
    schema_field = next(
        field for field in source_config.fields if isinstance(field, SourceFieldInputConfig) and field.name == "schema"
    )

    assert schema_field.required is True
    assert schema_field.label == "Schema"
    assert schema_field.caption is None
