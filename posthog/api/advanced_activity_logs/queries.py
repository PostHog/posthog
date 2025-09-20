from typing import Literal

SMALL_ORG_THRESHOLD = 20000  # Above this many log records, we do sampling and batching
BATCH_SIZE = 10000
SAMPLING_PERCENTAGE = 50.0


class QueryBuilder:
    @staticmethod
    def build_queries(
        organization_id: str, type: Literal["full", "batched_sampling"] = "full"
    ) -> list[tuple[str, list[str]]]:
        sampling_clause = ""
        if type == "batched_sampling":
            sampling_clause = f"TABLESAMPLE SYSTEM ({SAMPLING_PERCENTAGE})"

        queries = []

        query1 = f"""
            WITH filtered_data AS (
                SELECT scope, detail
                FROM posthog_activitylog {sampling_clause}
                WHERE organization_id = %s
                AND detail IS NOT NULL
                AND jsonb_typeof(detail) = 'object'
            )
            SELECT scope, field_path, array_agg(DISTINCT field_type ORDER BY field_type) as field_types
            FROM (
                SELECT scope, k1 as field_path, jsonb_typeof(detail->k1) as field_type
                FROM filtered_data, jsonb_object_keys(detail) as k1
                WHERE jsonb_typeof(detail->k1) IN ('string', 'number', 'boolean', 'array', 'object')

                UNION ALL

                SELECT scope, k1 || '.' || k2 as field_path, jsonb_typeof(detail->k1->k2) as field_type
                FROM filtered_data, jsonb_object_keys(detail) as k1, jsonb_object_keys(detail->k1) as k2
                WHERE jsonb_typeof(detail->k1) = 'object'
                AND jsonb_typeof(detail->k1->k2) IN ('string', 'number', 'boolean', 'array', 'object')

                UNION ALL

                SELECT scope, k1 || '[]' as field_path, jsonb_typeof(elem1.value) as field_type
                FROM filtered_data, jsonb_object_keys(detail) as k1, jsonb_array_elements(detail->k1) as elem1
                WHERE jsonb_typeof(detail->k1) = 'array'
                AND jsonb_typeof(elem1.value) IN ('string', 'number', 'boolean', 'array', 'object')

                UNION ALL

                SELECT scope, k1 || '.' || k2 || '.' || k3 as field_path, jsonb_typeof(detail->k1->k2->k3) as field_type
                FROM filtered_data, jsonb_object_keys(detail) as k1, jsonb_object_keys(detail->k1) as k2, jsonb_object_keys(detail->k1->k2) as k3
                WHERE jsonb_typeof(detail->k1) = 'object'
                AND jsonb_typeof(detail->k1->k2) = 'object'
                AND jsonb_typeof(detail->k1->k2->k3) IN ('string', 'number', 'boolean', 'array', 'object')

                UNION ALL

                SELECT scope, k1 || '.' || k2 || '[]' as field_path, jsonb_typeof(elem2.value) as field_type
                FROM filtered_data, jsonb_object_keys(detail) as k1, jsonb_object_keys(detail->k1) as k2, jsonb_array_elements(detail->k1->k2) as elem2
                WHERE jsonb_typeof(detail->k1) = 'object'
                AND jsonb_typeof(detail->k1->k2) = 'array'
                AND jsonb_typeof(elem2.value) IN ('string', 'number', 'boolean', 'array', 'object')

                UNION ALL

                SELECT scope, k1 || '[].' || k2_arr as field_path, jsonb_typeof(elem1.value->k2_arr) as field_type
                FROM filtered_data, jsonb_object_keys(detail) as k1, jsonb_array_elements(detail->k1) as elem1, jsonb_object_keys(elem1.value) as k2_arr
                WHERE jsonb_typeof(detail->k1) = 'array'
                AND jsonb_typeof(elem1.value) = 'object'
                AND jsonb_typeof(elem1.value->k2_arr) IN ('string', 'number', 'boolean', 'array', 'object')

                UNION ALL

                SELECT scope, k1 || '[].' || k2_arr || '[]' as field_path, jsonb_typeof(elem2_arr.value) as field_type
                FROM filtered_data, jsonb_object_keys(detail) as k1, jsonb_array_elements(detail->k1) as elem1,
                     jsonb_object_keys(elem1.value) as k2_arr, jsonb_array_elements(elem1.value->k2_arr) as elem2_arr
                WHERE jsonb_typeof(detail->k1) = 'array'
                AND jsonb_typeof(elem1.value) = 'object'
                AND jsonb_typeof(elem1.value->k2_arr) = 'array'
                AND jsonb_typeof(elem2_arr.value) IN ('string', 'number', 'boolean', 'array', 'object')
            ) all_fields
            WHERE field_path IS NOT NULL
            GROUP BY scope, field_path
            HAVING array_length(array_agg(DISTINCT field_type ORDER BY field_type), 1) > 0
            ORDER BY scope, field_path
        """
        queries.append((query1, [organization_id]))

        # Always include deep patterns query
        query2 = f"""
                WITH filtered_data AS (
                    SELECT scope, detail
                    FROM posthog_activitylog {sampling_clause}
                    WHERE organization_id = %s
                    AND detail IS NOT NULL
                    AND jsonb_typeof(detail) = 'object'
                )
                SELECT scope, field_path, array_agg(DISTINCT field_type ORDER BY field_type) as field_types
                FROM (
                    SELECT scope, k1 || '[].' || k2 || '.' || k3 || '[].' || k4 || '[].' || k5 as field_path,
                           jsonb_typeof(elem4.value->k5) as field_type
                    FROM filtered_data
                    CROSS JOIN LATERAL jsonb_object_keys(detail) as k1
                    CROSS JOIN LATERAL jsonb_array_elements(detail->k1) as elem1
                    CROSS JOIN LATERAL jsonb_object_keys(elem1.value) as k2
                    CROSS JOIN LATERAL jsonb_object_keys(elem1.value->k2) as k3
                    CROSS JOIN LATERAL jsonb_array_elements(elem1.value->k2->k3) as elem3
                    CROSS JOIN LATERAL jsonb_object_keys(elem3.value) as k4
                    CROSS JOIN LATERAL jsonb_array_elements(elem3.value->k4) as elem4
                    CROSS JOIN LATERAL jsonb_object_keys(elem4.value) as k5
                    WHERE jsonb_typeof(detail->k1) = 'array'
                    AND jsonb_typeof(elem1.value) = 'object'
                    AND jsonb_typeof(elem1.value->k2) = 'object'
                    AND jsonb_typeof(elem1.value->k2->k3) = 'array'
                    AND jsonb_typeof(elem3.value) = 'object'
                    AND jsonb_typeof(elem3.value->k4) = 'array'
                    AND jsonb_typeof(elem4.value) = 'object'
                    AND jsonb_typeof(elem4.value->k5) IN ('string', 'number', 'boolean', 'array', 'object')

                    UNION ALL

                    SELECT scope, k1 || '[].' || k2 || '.' || k3 as field_path,
                           jsonb_typeof(elem1.value->k2->k3) as field_type
                    FROM filtered_data
                    CROSS JOIN LATERAL jsonb_object_keys(detail) as k1
                    CROSS JOIN LATERAL jsonb_array_elements(detail->k1) as elem1
                    CROSS JOIN LATERAL jsonb_object_keys(elem1.value) as k2
                    CROSS JOIN LATERAL jsonb_object_keys(elem1.value->k2) as k3
                    WHERE jsonb_typeof(detail->k1) = 'array'
                    AND jsonb_typeof(elem1.value) = 'object'
                    AND jsonb_typeof(elem1.value->k2) = 'object'
                    AND jsonb_typeof(elem1.value->k2->k3) IN ('string', 'number', 'boolean', 'array', 'object')

                    UNION ALL

                    SELECT scope, k1 || '.' || k2 || '[].' || k3 || '.' || k4 || '[]' as field_path,
                           jsonb_typeof(elem4.value) as field_type
                    FROM filtered_data
                    CROSS JOIN LATERAL jsonb_object_keys(detail) as k1
                    CROSS JOIN LATERAL jsonb_object_keys(detail->k1) as k2
                    CROSS JOIN LATERAL jsonb_array_elements(detail->k1->k2) as elem2
                    CROSS JOIN LATERAL jsonb_object_keys(elem2.value) as k3
                    CROSS JOIN LATERAL jsonb_object_keys(elem2.value->k3) as k4
                    CROSS JOIN LATERAL jsonb_array_elements(elem2.value->k3->k4) as elem4
                    WHERE jsonb_typeof(detail->k1) = 'object'
                    AND jsonb_typeof(detail->k1->k2) = 'array'
                    AND jsonb_typeof(elem2.value) = 'object'
                    AND jsonb_typeof(elem2.value->k3) = 'object'
                    AND jsonb_typeof(elem2.value->k3->k4) = 'array'
                    AND jsonb_typeof(elem4.value) IN ('string', 'number', 'boolean', 'array', 'object')

                    UNION ALL

                    SELECT scope, k1 || '[].' || k2 || '.' || k3 || '[].' || k4 || '[].' || k5 || '.' || k6 as field_path,
                           jsonb_typeof(elem4.value->k5->k6) as field_type
                    FROM filtered_data
                    CROSS JOIN LATERAL jsonb_object_keys(detail) as k1
                    CROSS JOIN LATERAL jsonb_array_elements(detail->k1) as elem1
                    CROSS JOIN LATERAL jsonb_object_keys(elem1.value) as k2
                    CROSS JOIN LATERAL jsonb_object_keys(elem1.value->k2) as k3
                    CROSS JOIN LATERAL jsonb_array_elements(elem1.value->k2->k3) as elem3
                    CROSS JOIN LATERAL jsonb_object_keys(elem3.value) as k4
                    CROSS JOIN LATERAL jsonb_array_elements(elem3.value->k4) as elem4
                    CROSS JOIN LATERAL jsonb_object_keys(elem4.value) as k5
                    CROSS JOIN LATERAL jsonb_object_keys(elem4.value->k5) as k6
                    WHERE jsonb_typeof(detail->k1) = 'array'
                    AND jsonb_typeof(elem1.value) = 'object'
                    AND jsonb_typeof(elem1.value->k2) = 'object'
                    AND jsonb_typeof(elem1.value->k2->k3) = 'array'
                    AND jsonb_typeof(elem3.value) = 'object'
                    AND jsonb_typeof(elem3.value->k4) = 'array'
                    AND jsonb_typeof(elem4.value) = 'object'
                    AND jsonb_typeof(elem4.value->k5) = 'object'
                    AND jsonb_typeof(elem4.value->k5->k6) IN ('string', 'number', 'boolean', 'array', 'object')
                ) deep_fields
                GROUP BY scope, field_path
                ORDER BY scope, field_path
            """
        queries.append((query2, [organization_id]))

        return queries

    @staticmethod
    def build_top_level_fields_query(
        organization_id: str, type: Literal["full", "batched_sampling"] = "full"
    ) -> tuple[str, list[str]]:
        sampling_clause = ""
        if type == "batched_sampling":
            sampling_clause = f"TABLESAMPLE SYSTEM ({SAMPLING_PERCENTAGE})"

        query = f"""
        SELECT
            scope,
            field_name,
            array_agg(DISTINCT jsonb_typeof(detail->field_name)) as field_types
        FROM (
            SELECT
                scope,
                jsonb_object_keys(detail) as field_name,
                detail
            FROM posthog_activitylog {sampling_clause}
            WHERE organization_id = %s
            AND detail IS NOT NULL
            AND jsonb_typeof(detail) = 'object'
        ) field_data
        WHERE jsonb_typeof(detail->field_name) IN ('string', 'number', 'boolean')
        GROUP BY scope, field_name
        HAVING COUNT(detail->>field_name) >= 1
        ORDER BY scope, field_name
        """
        return query, [organization_id]


# Backwards compatibility alias
QueryBuilder = QueryBuilder
