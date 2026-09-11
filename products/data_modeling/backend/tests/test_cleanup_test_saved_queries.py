from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.tasks.cleanup_test_saved_queries import cleanup_expired_test_saved_queries

pytestmark = pytest.mark.django_db


def _expired_test_saved_query() -> DataWarehouseSavedQuery:
    team = Team.objects.create(organization=Organization.objects.create(name="org"), name="t")
    return DataWarehouseSavedQuery.objects.create(
        team=team,
        name="expired_view",
        query={"kind": "HogQLQuery", "query": "select 1"},
        is_test=True,
        expires_at=timezone.now() - timedelta(days=1),
    )


@parameterized.expand(
    [
        ("deleted", None, False),
        ("never_materialized", FileNotFoundError(), False),
        ("s3_unreachable", RuntimeError("Unable to locate credentials"), True),
    ]
)
def test_expired_test_saved_query_survives_when_its_s3_data_does(
    _name: str, delete_side_effect: Exception | None, expect_survives: bool
) -> None:
    saved_query = _expired_test_saved_query()

    client = MagicMock()
    client.delete.side_effect = delete_side_effect
    with patch("products.data_warehouse.backend.facade.api.get_s3_client", return_value=client):
        cleanup_expired_test_saved_queries()

    assert DataWarehouseSavedQuery.objects.filter(id=saved_query.id).exists() is expect_survives
