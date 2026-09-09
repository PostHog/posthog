# Test cases for clickhouse-migrations-use-run-mode rule.
# ruff: noqa: F821, E501
from posthog import settings
from posthog.run_mode import RunMode, run_mode

# ruleid: clickhouse-migrations-use-run-mode
_gate = settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")

# ruleid: clickhouse-migrations-use-run-mode
_region_is_us = settings.CLOUD_DEPLOYMENT == "US"

# ok: clickhouse-migrations-use-run-mode
_ok_gate = run_mode().is_deployed_cloud

# ok: clickhouse-migrations-use-run-mode
_ok_prod = run_mode().is_prod_cloud

# ok: clickhouse-migrations-use-run-mode
_ok_region = run_mode() is RunMode.CLOUD_US
