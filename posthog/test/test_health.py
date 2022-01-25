from unittest.mock import patch

import pytest
from django.http import HttpResponse

from ee.kafka_client.client import TestKafkaProducer


@pytest.mark.django_db
def test_healthcheck_endpoint_fails_for_kafka_connection_issues(client):
    resp = get_healthcheck(client)
    assert resp.status_code == 200

    # Simulate a failure in Kafka connection by mocking bootstrap_connected
    with patch.object(TestKafkaProducer, "bootstrap_connected") as producer_connected_mock:
        producer_connected_mock.return_value = False
        resp = get_healthcheck(client)

        assert resp.status_code == 503


def get_healthcheck(client) -> HttpResponse:
    return client.get("/_health")
