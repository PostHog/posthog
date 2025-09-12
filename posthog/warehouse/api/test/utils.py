from typing import Any

from django.test.client import Client as HttpClient


def create_external_data_source_ok(client: HttpClient, team_id: int) -> int:
    """Create an external data source and return the id."""
    response = client.post(
        f"/api/environments/{team_id}/external_data_sources/",
        data={
            "source_type": "Stripe",
            "payload": {
                "stripe_secret_key": "sk_test_123",
                "schemas": [
                    {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                    {"name": "Subscription", "should_sync": True, "sync_type": "full_refresh"},
                    {"name": "Customer", "should_sync": True, "sync_type": "full_refresh"},
                    {"name": "Product", "should_sync": True, "sync_type": "full_refresh"},
                    {"name": "Price", "should_sync": True, "sync_type": "full_refresh"},
                    {"name": "Invoice", "should_sync": True, "sync_type": "full_refresh"},
                    {
                        "name": "Charge",
                        "should_sync": False,
                        "sync_type": "full_refresh",
                        "sync_time_of_day": "01:00:00",
                    },
                ],
            },
        },
        content_type="application/json",
    )
    payload: dict[str, Any] = response.json()

    assert response.status_code == 201
    return payload["id"]
