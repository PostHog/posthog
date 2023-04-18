# Test the Customer Data Pipeline endpoints. This doesn't do an in depth test of
# the requests and response. The endpoints at the time of writing are just
# proxies to the Customer Data Pipeline service. We simply mock the requests
# library to allow us to mock the response and check that the right requests are
# made.

from django.conf import settings
from django.test.client import Client
import jwt
import pytest
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
import responses


@pytest.mark.django_db
def test_returns_401_if_not_authenticated(client: Client):
    response = client.get("/api/projects/1/destination")
    assert response.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path,status_code",
    [
        ("GET", "destination-types", 200),
        ("GET", "destinations/abc-123", 200),
        ("POST", "destinations", 201),
        ("PUT", "destinations/abc-123", 200),
        ("DELETE", "destinations/abc-123", 204),
    ],
)
def test_proxies_customer_data_pipeline_endpoints(
    client: Client,
    method: str,
    path: str,
    status_code: int,
):
    organization = create_organization(name="test")
    team = create_team(organization=organization)
    user = create_user(email="test@posthog.com", password="1234", organization=organization)

    client.force_login(user)

    path = f"/api/projects/{team.pk}/{path}"

    with responses.RequestsMock() as mock_requests:
        mock_requests.add(
            method,
            f"{settings.CDP_API_URL}{path}",
            json={"data": "test"},
            status=status_code,
        )

        response = client.generic(method=method, path=path)
        assert response.status_code == status_code

        # Make sure the request was made with a JWT token in the Authorization
        # header. We parse the token with the jwt library to ensure it's valid.
        assert len(mock_requests.calls) == 1
        assert mock_requests.calls[0].request.headers["Authorization"].startswith("Bearer ")

        # Make sure the request was made with the right user ID and project IDs
        token = mock_requests.calls[0].request.headers["Authorization"].split(" ")[1]
        decoded_token = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        assert decoded_token["userId"] == user.pk
        assert decoded_token["projectIds"] == [team.pk]
