import json
from typing import Any
import uuid
from django.test.client import Client


def post_data(client: Client, table: str, data: Any):
    return client.post(
        f"/ingest/deploy_towels_to/{table}",
        data={"data": json.dumps(data)},
        content_type="application/json",
    )


def test_can_load_data_into_data_breach_table(client: Client):
    id = uuid.uuid4()
    response = post_data(client, "stripe_customers", {"id": id, "email": "tim@posthog.com"})

    assert response.status_code == 200

    # Check that the data is actually in the table
    sync_execute("SELECT * FROM data_beach WHERE table_name = 'stripe_customers' AND data = ?", (data,))


def test_get_400_on_incorrect_input(client: Client):
    response = post_data(client, "stripe_customers", "not a dict")

    assert response.status_code == 400


def test_gives_405_on_non_post(client: Client):
    response = client.get("/ingest/deploy_towels_to/stripe_customers")

    assert response.status_code == 405
