from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.team import Team
from posthog.models.user import User

from products.data_catalog.evals.seeders import _require_incident_warehouse_paths


class TestGovernedMetricEvalSeeders:
    @parameterized.expand(["paid_bills", "extended_properties"])
    def test_missing_incident_warehouse_path_is_an_infrastructure_error(self, missing_table: str) -> None:
        tables = [
            SimpleNamespace(name=name, url_pattern="s3://warehouse/{team_id}", credential_id=1)
            for name in ("paid_bills", "extended_properties")
            if name != missing_table
        ]

        with (
            patch("products.data_catalog.evals.seeders.DataWarehouseTable.objects.queryable") as queryable,
            pytest.raises(RuntimeError, match=missing_table),
        ):
            queryable.return_value.filter.return_value = tables
            _require_incident_warehouse_paths(cast(Team, SimpleNamespace()), cast(User, SimpleNamespace()))
