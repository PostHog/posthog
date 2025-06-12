import json
import logging
import os
import sys
from clickhouse_driver import Client

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import LATEST_VERSIONS from posthog if needed, or define your own if running standalone
try:
    from posthog.schema_migrations import LATEST_VERSIONS
except ImportError:
    LATEST_VERSIONS = {}

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(message)s")


CLICKHOUSE_QUERY = """
SELECT log_comment, JSONExtractRaw(log_comment, 'query') as query
FROM system.query_log
WHERE type > 1
AND JSONExtractRaw(log_comment, 'query') != ''
"""


def run_clickhouse_query(query):
    host = os.environ.get("CLICKHOUSE_HOST", "localhost")
    port = int(os.environ.get("CLICKHOUSE_PORT", 9000))
    user = os.environ.get("CLICKHOUSE_USER", "default")
    password = os.environ.get("CLICKHOUSE_PASSWORD", "")
    database = os.environ.get("CLICKHOUSE_DATABASE", "default")
    client = Client(host=host, port=port, user=user, password=password, database=database)
    return client.execute(query)


def validate_versions():
    output = run_clickhouse_query(CLICKHOUSE_QUERY)
    for row in output:
        try:
            log_comment, query_json = row
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
