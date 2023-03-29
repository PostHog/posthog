import json
from typing import Any
import uuid
from django.test.client import Client
import pytest
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from posthog.clickhouse.client.execute import sync_execute


def post_data(client: Client, token: str, table_name: str, id: str, data: Any):
    # Make a POST request to the data beach endpoint, using the given token
    # and table name, id, and the given data. We simply pass the token along with
    # the body of the request, along with the id. The data is passed as a string
    # which we attempt to insert into the table with no validation, such that we
    # do not need to spend any time parsing it.
    return client.post(
        f"/ingest/deploy_towels_to/{table_name}/",
        data={"id": id, "token": token, "data": json.dumps(data)},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_can_load_data_into_data_breach_table(client: Client):
    organization = create_organization(name="test")
    team = create_team(organization=organization)
    id = uuid.uuid4()
    response = post_data(
        client=client, token=team.api_token, table_name="stripe_customers", id=id, data={"email": "tim@posthog.com"}
    )

    assert response.status_code == 200

    # Check that the data is actually in the table
    results = sync_execute(
        f"""
        SELECT * 
        FROM data_beach 
        WHERE table_name = 'stripe_customers' 
            AND team_id = {team.pk}
            AND id = '{id}'
    """
    )

    assert len(results) == 1


@pytest.mark.django_db
def test_get_403_for_invalid_token(client: Client):
    response = post_data(
        client=client, token="invalid", table_name="stripe_customers", id="some-id", data={"email": "tim@posthog.com"}
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_get_400_on_incorrect_input(client: Client):
    organization = create_organization(name="test")
    team = create_team(organization=organization)
    response = post_data(
        client=client, token=team.api_token, table_name="stripe_customers", id="", data={"email": "tim@posthog.com"}
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_gives_405_on_non_post(client: Client):
    response = client.get("/ingest/deploy_towels_to/stripe_customers/")

    assert response.status_code == 405
