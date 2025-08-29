# Traverse depth when discovering nested fields
MAX_NESTED_DEPTH = 3

# Recursive query to discover nested fields at any depth
NESTED_FIELDS_RECURSIVE_QUERY = """
WITH RECURSIVE field_paths AS (
    -- Base case: top-level fields
    SELECT
        scope,
        detail,
        jsonb_object_keys(detail) as field_name,
        jsonb_object_keys(detail) as field_path,
        detail->jsonb_object_keys(detail) as field_value,
        1 as depth
    FROM posthog_activitylog
    WHERE organization_id = %s
    AND scope IS NOT NULL
    AND detail IS NOT NULL
    AND jsonb_typeof(detail) = 'object'

    UNION ALL

    -- Recursive case: traverse deeper into objects only
    SELECT
        fp.scope,
        fp.detail,
        jsonb_object_keys(fp.field_value) as field_name,
        fp.field_path || '.' || jsonb_object_keys(fp.field_value) as field_path,
        fp.field_value->jsonb_object_keys(fp.field_value) as field_value,
        fp.depth + 1 as depth
    FROM field_paths fp
    WHERE fp.depth < %s  -- MAX_NESTED_DEPTH param
    AND jsonb_typeof(fp.field_value) = 'object'
)
SELECT
    scope,
    field_path,
    array_agg(DISTINCT jsonb_typeof(field_value)) as field_types
FROM field_paths
WHERE jsonb_typeof(field_value) IN ('string', 'number', 'boolean')
GROUP BY scope, field_path
HAVING COUNT(DISTINCT
    CASE
        WHEN jsonb_typeof(field_value) = 'string' THEN field_value #>> '{}'
        WHEN jsonb_typeof(field_value) = 'number' THEN field_value::text
        WHEN jsonb_typeof(field_value) = 'boolean' THEN field_value::text
    END
) > 1
ORDER BY scope, field_path
"""

# Query to discover top-level fields (e.g., name, label)
TOP_LEVEL_FIELDS_QUERY = """
SELECT
    scope,
    field_name,
    array_agg(DISTINCT jsonb_typeof(detail->field_name)) as field_types
FROM (
    SELECT
        scope,
        jsonb_object_keys(detail) as field_name,
        detail
    FROM posthog_activitylog
    WHERE organization_id = %s
    AND scope IS NOT NULL
    AND detail IS NOT NULL
    AND jsonb_typeof(detail) = 'object'
) field_data
WHERE jsonb_typeof(detail->field_name) IN ('string', 'number', 'boolean')
GROUP BY scope, field_name
HAVING COUNT(DISTINCT detail->>field_name) > 1
ORDER BY scope, field_name
"""


class QueryBuilder:
    @staticmethod
    def build_nested_fields_query(
        organization_id: str, max_depth: int = MAX_NESTED_DEPTH
    ) -> tuple[str, list[str | int]]:
        """Build query to find nested fields with their types."""
        return NESTED_FIELDS_RECURSIVE_QUERY, [organization_id, max_depth]

    @staticmethod
    def build_top_level_fields_query(organization_id: str) -> tuple[str, list[str]]:
        """Build query to find top-level scalar fields with their types."""
        return TOP_LEVEL_FIELDS_QUERY, [organization_id]
