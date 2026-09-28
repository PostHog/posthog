import datetime as dt

import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.batch_exports.backend.models.batch_export import BatchExportRun
from products.batch_exports.backend.tests.api.fixtures import create_batch_export, create_destination, create_run

pytestmark = [pytest.mark.django_db]


@pytest.mark.parametrize(
    "route,scopes,expected_status",
    [
        ("batch_export", ["batch_export:read"], status.HTTP_200_OK),
        ("batch_export", ["feature_flag:read"], status.HTTP_403_FORBIDDEN),
        ("batch_export_run", ["feature_flag:read"], status.HTTP_403_FORBIDDEN),
    ],
)
def test_log_entries_with_scoped_personal_api_key(
    client: HttpClient, team, user, route: str, scopes: list[str], expected_status: int
):
    batch_export = create_batch_export(team, create_destination())
    now = dt.datetime.now(dt.UTC)
    run = create_run(
        batch_export,
        status=BatchExportRun.Status.COMPLETED,
        data_interval_start=now - dt.timedelta(hours=1),
        data_interval_end=now,
    )
    key_value = generate_random_token_personal()
    PersonalAPIKey.objects.create(label="Test key", user=user, secure_value=hash_key_value(key_value), scopes=scopes)
    path = f"/api/projects/{team.pk}/batch_exports/{batch_export.id}"
    if route == "batch_export_run":
        path += f"/runs/{run.id}"

    response = client.get(f"{path}/logs", headers={"authorization": f"Bearer {key_value}"})

    assert response.status_code == expected_status, response.json()
