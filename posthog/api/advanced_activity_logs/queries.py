# Traverse depth when discovering nested fields
MAX_NESTED_DEPTH = 6

# Query templates for different path patterns
QUERY_TEMPLATES = {
    "object_path": """
        SELECT
            scope,
            {field_path} as field_path,
            array_agg(DISTINCT jsonb_typeof({field_value})) as field_types
        FROM posthog_activitylog{lateral_joins}
        WHERE organization_id = %s
        AND detail IS NOT NULL
        AND jsonb_typeof(detail) = 'object'
        {type_conditions}
        AND jsonb_typeof({field_value}) IN ('string', 'number', 'boolean')
        GROUP BY scope, {field_path}
        HAVING COUNT({having_expr}) >= 1
        ORDER BY scope, {field_path}
    """,
    "array_elements": """
        SELECT
            scope,
            {field_path} as field_path,
            array_agg(DISTINCT jsonb_typeof({field_value})) as field_types
        FROM posthog_activitylog{lateral_joins}
        WHERE organization_id = %s
        AND detail IS NOT NULL
        AND jsonb_typeof(detail) = 'object'
        {type_conditions}
        AND jsonb_typeof({field_value}) IN ('string', 'number', 'boolean')
        GROUP BY scope, {field_path_group}
        HAVING COUNT({having_expr}) >= 1
        ORDER BY scope, {field_path_group}
    """,
}


class PathBuilder:
    @staticmethod
    def build_object_path(depth: int) -> dict:
        """Build path data for pure object traversal: field.subfield.subsubfield"""
        if depth < 1 or depth > MAX_NESTED_DEPTH:
            raise ValueError(f"Depth must be between 1 and {MAX_NESTED_DEPTH}")

        keys = [f"k{i}" for i in range(1, depth + 1)]

        # Build lateral joins: LATERAL jsonb_object_keys(detail) AS k1, ...
        lateral_joins = ", LATERAL jsonb_object_keys(detail) AS k1"
        for i in range(2, depth + 1):
            parent_path = "detail" + "".join(f"->k{j}" for j in range(1, i))
            lateral_joins += f", LATERAL jsonb_object_keys({parent_path}) AS k{i}"

        # Build type conditions for intermediate objects
        type_conditions = []
        path = "detail"
        for key in keys[:-1]:
            path += f"->{key}"
            type_conditions.append(f"jsonb_typeof({path}) = 'object'")

        type_condition_str = " AND " + " AND ".join(type_conditions) if type_conditions else ""

        # Build field value accessor and having expression
        field_value = "detail" + "".join(f"->k{i}" for i in range(1, depth + 1))
        having_path = "detail" + "".join(f"->k{i}" for i in range(1, depth))
        having_expr = f"({having_path})->>{keys[-1]}" if depth > 1 else f"detail->>k1"

        return {
            "field_path": " || '.' || ".join(keys),
            "field_value": field_value,
            "lateral_joins": lateral_joins,
            "type_conditions": type_condition_str,
            "having_expr": having_expr,
        }

    @staticmethod
    def build_array_path(array_positions: list[int], total_depth: int) -> dict:
        """Build path data for paths containing arrays at specific positions"""
        if not array_positions or total_depth < 1 or max(array_positions) > total_depth:
            raise ValueError("Invalid array positions or depth")

        # Build the path components and lateral joins
        lateral_joins = ""
        type_conditions = []
        field_path_parts = []
        current_path = "detail"
        keys_defined = set()

        for i in range(1, total_depth + 1):
            if i in array_positions:
                # Array position - need key first, then array elements
                if i not in keys_defined:
                    if i == 1:
                        lateral_joins += f", LATERAL jsonb_object_keys(detail) AS k{i}"
                    elif (i - 1) in array_positions:
                        # Previous was array, get keys from array elements
                        lateral_joins += f", LATERAL jsonb_object_keys(elem{i-1}.value) AS k{i}"
                        type_conditions.append(f"jsonb_typeof(elem{i-1}.value) = 'object'")
                    else:
                        # Previous was object
                        lateral_joins += f", LATERAL jsonb_object_keys({current_path}) AS k{i}"
                        type_conditions.append(f"jsonb_typeof({current_path}) = 'object'")
                    keys_defined.add(i)

                # Now add the array elements
                if i == 1:
                    lateral_joins += f", LATERAL jsonb_array_elements(detail->k{i}) AS elem{i}"
                    type_conditions.append(f"jsonb_typeof(detail->k{i}) = 'array'")
                elif (i - 1) in array_positions:
                    lateral_joins += f", LATERAL jsonb_array_elements(elem{i-1}.value->k{i}) AS elem{i}"
                    type_conditions.append(f"jsonb_typeof(elem{i-1}.value->k{i}) = 'array'")
                else:
                    lateral_joins += f", LATERAL jsonb_array_elements({current_path}->k{i}) AS elem{i}"
                    type_conditions.append(f"jsonb_typeof({current_path}->k{i}) = 'array'")

                current_path = f"elem{i}.value"
                field_path_parts.append(f"k{i} || '[]'")
            else:
                # Regular object key
                if i not in keys_defined:
                    if i == 1:
                        lateral_joins += f", LATERAL jsonb_object_keys(detail) AS k{i}"
                    elif (i - 1) in array_positions:
                        # Previous was array, get keys from array elements
                        lateral_joins += f", LATERAL jsonb_object_keys(elem{i-1}.value) AS k{i}"
                        type_conditions.append(f"jsonb_typeof(elem{i-1}.value) = 'object'")
                    else:
                        # Previous was object
                        lateral_joins += f", LATERAL jsonb_object_keys({current_path}) AS k{i}"
                        type_conditions.append(f"jsonb_typeof({current_path}) = 'object'")
                    keys_defined.add(i)

                field_path_parts.append(f"k{i}")
                if i < total_depth:
                    if (i - 1) in array_positions:
                        current_path = f"elem{i-1}.value->k{i}"
                    else:
                        current_path += f"->k{i}"

        # Build final field value and path
        field_value = current_path + (f"->k{total_depth}" if total_depth not in array_positions else "")
        field_path = " || '.' || ".join(field_path_parts)

        # Build having expression
        if total_depth in array_positions:
            having_expr = f"{field_value}::text"
        else:
            having_expr = f"({current_path})->>{f'k{total_depth}'}"

        type_condition_str = " AND " + " AND ".join(type_conditions) if type_conditions else ""

        # Group by path components (without array element references)
        field_path_group = " || '.' || ".join(
            [f"k{i}" if i not in array_positions else f"k{i} || '[]'" for i in range(1, total_depth + 1)]
        )

        return {
            "field_path": field_path,
            "field_value": field_value,
            "lateral_joins": lateral_joins,
            "type_conditions": type_condition_str,
            "having_expr": having_expr,
            "field_path_group": field_path_group,
        }


class QueryBuilder:
    @staticmethod
    def build_nested_fields_queries(
        organization_id: str, max_depth: int = MAX_NESTED_DEPTH
    ) -> list[tuple[str, list[str]]]:
        """Build all queries to discover nested fields"""
        queries = []

        # Object-only paths: field, field.subfield, field.sub.subsub, etc.
        for depth in range(1, max_depth + 1):
            try:
                path_data = PathBuilder.build_object_path(depth)
                query = QUERY_TEMPLATES["object_path"].format(**path_data)
                queries.append((query, [organization_id]))
            except ValueError:
                continue

        # Array paths: field[], field[].sub, field.sub[], field[].sub.subsub, etc.
        for depth in range(1, max_depth + 1):
            # Try array at each possible position
            for array_pos in range(1, depth + 1):
                try:
                    path_data = PathBuilder.build_array_path([array_pos], depth)
                    query = QUERY_TEMPLATES["array_elements"].format(**path_data)
                    queries.append((query, [organization_id]))
                except ValueError:
                    continue

        # Special patterns with multiple arrays (limited to avoid explosion)
        if max_depth >= 3:
            # Pattern: field[].sub[] - nested arrays
            try:
                path_data = PathBuilder.build_array_path([1, 2], 2)
                query = QUERY_TEMPLATES["array_elements"].format(**path_data)
                queries.append((query, [organization_id]))
            except ValueError:
                pass

        # Add standalone array field patterns that were in original
        standalone_query = """
        SELECT
            scope,
            k1 || '[].' || k2 as field_path,
            array_agg(DISTINCT jsonb_typeof(elem.value->k2)) as field_types
        FROM posthog_activitylog,
             LATERAL jsonb_object_keys(detail) AS k1,
             LATERAL jsonb_array_elements(detail->k1) AS elem,
             LATERAL jsonb_object_keys(elem.value) AS k2
        WHERE organization_id = %s
        AND detail IS NOT NULL
        AND jsonb_typeof(detail) = 'object'
        AND jsonb_typeof(detail->k1) = 'array'
        AND jsonb_typeof(elem.value) = 'object'
        AND jsonb_typeof(elem.value->k2) IN ('string', 'number', 'boolean')
        GROUP BY scope, k1, k2
        HAVING COUNT(elem.value->>k2) >= 1
        ORDER BY scope, k1, k2
        """
        queries.append((standalone_query, [organization_id]))

        return queries

    @staticmethod
    def build_top_level_fields_query(organization_id: str) -> tuple[str, list[str]]:
        """Build query to find top-level scalar fields with their types"""
        query = """
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
            AND detail IS NOT NULL
            AND jsonb_typeof(detail) = 'object'
        ) field_data
        WHERE jsonb_typeof(detail->field_name) IN ('string', 'number', 'boolean')
        GROUP BY scope, field_name
        HAVING COUNT(detail->>field_name) >= 1
        ORDER BY scope, field_name
        """
        return query, [organization_id]
