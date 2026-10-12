import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, create_autospec, patch

from openfga_sdk import AuthorizationModel, GetStoreResponse, ReadAuthorizationModelResponse
from openfga_sdk.exceptions import UnauthorizedException
from openfga_sdk.sync import OpenFgaClient
from parameterized import parameterized
from rest_framework import status
from urllib3 import HTTPConnectionPool
from urllib3.exceptions import MaxRetryError

STATUS_URL = "/api/authz/status/"
GET_OPENFGA_CLIENT = "products.authz.backend.logic.openfga_status.get_openfga_client"
API_URL_WITH_CREDENTIALS = "http://fga-user:fga-password@openfga.example.com:8080"
API_URL = "http://openfga.example.com:8080"
STORE_ID = "01HSTORE0000000000000000AA"
MODEL_ID = "01HMODEL0000000000000000AA"
STORE_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

UNREACHABLE: dict[str, Any] = {
    "reachable": False,
    "api_url": API_URL,
    "store_name": None,
    "store_id": None,
    "authorization_model_id": None,
}


class TestOpenFgaStatusAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.openfga = create_autospec(OpenFgaClient, instance=True)
        self.openfga.get_store_id.return_value = STORE_ID
        self.openfga.get_store.return_value = GetStoreResponse(
            id=STORE_ID, name="posthog-authz", created_at=STORE_CREATED_AT, updated_at=STORE_CREATED_AT
        )
        self.openfga.read_latest_authorization_model.return_value = ReadAuthorizationModelResponse(
            authorization_model=AuthorizationModel(id=MODEL_ID, schema_version="1.1", type_definitions=[])
        )

    @contextmanager
    def _patched_openfga(self, client_error: Exception | None = None) -> Iterator[MagicMock]:
        with (
            patch.dict(os.environ, {"OPENFGA_API_URL": API_URL_WITH_CREDENTIALS}),
            patch(GET_OPENFGA_CLIENT, return_value=self.openfga, side_effect=client_error) as get_openfga_client,
        ):
            yield get_openfga_client

    @parameterized.expand(
        [
            (
                "reachable",
                None,
                None,
                {
                    "reachable": True,
                    "api_url": API_URL,
                    "store_name": "posthog-authz",
                    "store_id": STORE_ID,
                    "authorization_model_id": MODEL_ID,
                    "error": None,
                },
                True,
            ),
            (
                "client_creation_fails",
                MaxRetryError(HTTPConnectionPool("openfga.example.com", 8080), "/stores"),
                None,
                {**UNREACHABLE, "error": "MaxRetryError"},
                False,
            ),
            (
                "request_fails",
                None,
                UnauthorizedException(status=401, reason="Unauthorized"),
                {**UNREACHABLE, "error": "UnauthorizedException"},
                True,
            ),
        ]
    )
    def test_staff_user_gets_openfga_status(
        self,
        _name: str,
        client_error: Exception | None,
        request_error: Exception | None,
        expected: dict[str, Any],
        client_closed: bool,
    ) -> None:
        self.user.is_staff = True
        self.user.save()
        self.openfga.get_store.side_effect = request_error

        with self._patched_openfga(client_error):
            response = self.client.get(STATUS_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == expected
        assert self.openfga.close.called == client_closed

    def test_non_staff_user_is_forbidden(self) -> None:
        with self._patched_openfga() as get_openfga_client:
            response = self.client.get(STATUS_URL)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        get_openfga_client.assert_not_called()
