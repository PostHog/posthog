#!/usr/bin/env python3
import re
import sys

files_to_fix = [
    "models/action/action.py",
    "hogql/test/test_action_to_expr.py", 
    "session_recordings/queries/utils.py",
    "hogql_queries/insights/lifecycle_query_runner.py",
    "hogql_queries/insights/stickiness_query_runner.py",
    "hogql_queries/insights/trends/trends_query_builder.py",
    "hogql_queries/insights/trends/calendar_heatmap_query_runner.py",
    "hogql_queries/insights/trends/trends_actors_query_builder.py",
    "hogql_queries/insights/funnels/base.py",
    "hogql_queries/experiments/base_query_utils.py",
    "hogql_queries/web_analytics/web_goals.py",
    "hogql_queries/web_analytics/web_analytics_query_runner.py",
    "hogql_queries/ai/event_taxonomy_query_runner.py"
]

for file_path in files_to_fix:
    full_path = file_path
    try:
        with open(full_path, 'r') as f:
            content = f.read()
        
        # Replace import line
        new_content = re.sub(
            r'from posthog\.hogql\.property import (.*)action_to_expr(.*)',
            r'from posthog.hogql.property import \1\2\nfrom posthog.hogql_queries.action_entity_conversion import action_to_expr',
            content
        )
        
        # Clean up any double commas or leading/trailing commas
        new_content = re.sub(r',\s*,', ',', new_content)
        new_content = re.sub(r'import\s*,', 'import', new_content) 
        new_content = re.sub(r',\s*\n', '\n', new_content)
        
        if new_content != content:
            with open(full_path, 'w') as f:
                f.write(new_content)
            print(f"Fixed {full_path}")
        else:
            print(f"No changes needed for {full_path}")
    except Exception as e:
        print(f"Error processing {full_path}: {e}")