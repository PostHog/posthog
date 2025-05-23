import json
import subprocess
import logging
import os
import sys

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from posthog.schema_migrations import LATEST_VERSIONS

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(message)s")


CLICKHOUSE_QUERY = """
SELECT log_comment, JSONExtractRaw(log_comment, 'query') as query
FROM system.query_log
WHERE type > 1
AND JSONExtractRaw(log_comment, 'query') != ''
"""


def run_clickhouse_query(query):
    result = subprocess.run(["clickhouse-client", "--query", query], capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"ERROR running ClickHouse query: {result.stderr}")
        exit(1)
    return result.stdout


def validate_versions():
    output = run_clickhouse_query(CLICKHOUSE_QUERY)
    for line in output.strip().split("\n"):
        # Expecting tab-separated log_comment and query
        try:
            log_comment, query_json = line.split("\t", 1)
        except ValueError:
            continue
        try:
            query_dict = json.loads(query_json)
        except Exception:
            continue
        if not isinstance(query_dict, dict):
            continue
        kind = query_dict.get("kind")
        if kind is None:
            continue
        expected_version = LATEST_VERSIONS.get(kind)
        actual_version = query_dict.get("version")
        if expected_version is not None:
            if actual_version != expected_version:
                logging.error(
                    f"ERROR: Version mismatch for kind '{kind}' in log_comment: {log_comment}\n  Expected: {expected_version}, Found: {actual_version}"
                )


if __name__ == "__main__":
    validate_versions()
