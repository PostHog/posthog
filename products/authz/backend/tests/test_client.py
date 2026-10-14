import os
from threading import Thread
from typing import cast

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from openfga_sdk.client.models import ClientCheckRequest
from parameterized import parameterized

from products.authz.backend.client import (
    Consistency,
    close_cached_openfga_client,
    get_openfga_client,
    pooled_openfga_client,
)

STORE_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class TestOpenFgaClient(SimpleTestCase):
    def setUp(self) -> None:
        close_cached_openfga_client()
        self.addCleanup(close_cached_openfga_client)
        self.enterContext(
            patch.dict(
                os.environ,
                {"OPENFGA_STORE_ID": STORE_ID, "OPENFGA_API_URL": "http://localhost:8080"},
            )
        )

    @parameterized.expand(
        [
            ("default", None, None, "MINIMIZE_LATENCY"),
            ("forced_request", None, "HIGHER_CONSISTENCY", "HIGHER_CONSISTENCY"),
            ("forced_client", "HIGHER_CONSISTENCY", None, "HIGHER_CONSISTENCY"),
        ]
    )
    def test_check_sends_default_or_explicit_consistency(
        self, _name: str, client_consistency: str | None, request_consistency: str | None, expected: str
    ) -> None:
        client = get_openfga_client(consistency="HIGHER_CONSISTENCY") if client_consistency else get_openfga_client()
        self.addCleanup(client.close)
        with patch.object(client._api, "check", return_value=MagicMock(allowed=True)) as check:
            assert client.check(
                ClientCheckRequest(user="user:1", relation="can_view", object="dashboard:1"),
                {"consistency": request_consistency} if request_consistency else None,
            ).allowed
        assert check.call_args.kwargs["body"].consistency == expected

    def test_pooled_default_consistency_does_not_leak_between_scopes(self) -> None:
        consistencies: tuple[Consistency, ...] = ("HIGHER_CONSISTENCY", "MINIMIZE_LATENCY")
        for consistency in consistencies:
            with pooled_openfga_client(consistency=consistency) as client:
                with patch.object(client._api, "check", return_value=MagicMock(allowed=True)) as check:
                    client.check(ClientCheckRequest(user="user:1", relation="can_view", object="dashboard:1"))
                assert check.call_args.kwargs["body"].consistency == consistency

    @parameterized.expand(
        [
            ("OPENFGA_API_URL", "http://localhost:8082"),
            ("OPENFGA_API_TOKEN", "fake-test-token"),
            ("OPENFGA_STORE_ID", "01ARZ3NDEKTSV4RRFFQ69G5FAW"),
            ("OPENFGA_STORE_NAME", "another-test-store"),
            ("OPENFGA_AUTHORIZATION_MODEL_ID", "01ARZ3NDEKTSV4RRFFQ69G5FAX"),
        ]
    )
    def test_reuses_connections_until_the_target_or_credentials_change(self, setting: str, value: str) -> None:
        clients = [MagicMock(), MagicMock()]
        with patch("products.authz.backend.client.OpenFgaClient", side_effect=clients):
            with pooled_openfga_client() as first:
                assert first is clients[0]
            with self.assertRaises(RuntimeError), pooled_openfga_client() as again:
                assert again is first
                raise RuntimeError("Check failed")
            clients[0].close.assert_not_called()
            with patch.dict(os.environ, {setting: value}), pooled_openfga_client() as changed:
                assert changed is clients[1]
                clients[0].close.assert_called_once()
            close_cached_openfga_client()
            clients[1].close.assert_called_once()

    def test_nested_target_does_not_close_the_borrowed_client(self) -> None:
        clients = [MagicMock(), MagicMock()]
        with patch("products.authz.backend.client.OpenFgaClient", side_effect=clients):
            with pooled_openfga_client() as first:
                with patch.dict(os.environ, {"OPENFGA_STORE_ID": "01ARZ3NDEKTSV4RRFFQ69G5FAW"}):
                    with pooled_openfga_client() as nested:
                        assert nested is clients[1]
                        clients[0].close.assert_not_called()
                    clients[1].close.assert_called_once()
                clients[0].close.assert_not_called()
            with pooled_openfga_client() as again:
                assert again is first

    def test_threads_and_forked_processes_do_not_share_clients(self) -> None:
        clients: list[MagicMock] = []

        def borrow() -> None:
            with pooled_openfga_client() as client:
                clients.append(cast(MagicMock, client))

        with patch("products.authz.backend.client.OpenFgaClient", side_effect=[MagicMock(), MagicMock(), MagicMock()]):
            borrow()
            thread = Thread(target=borrow)
            thread.start()
            thread.join()
            assert clients[0] is not clients[1]
            clients[0].close.assert_not_called()
            clients[1].close.assert_called_once()
            with patch("products.authz.backend.client.os.getpid", return_value=os.getpid() + 1):
                borrow()
            assert clients[2] is not clients[0]
            clients[0].close.assert_called_once()

    def test_missing_store_is_discovered_again_after_bootstrap(self) -> None:
        missing = MagicMock()
        missing.get_store_id.return_value = None
        missing.list_stores.return_value.stores = []
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("products.authz.backend.client.OpenFgaClient", side_effect=[missing, MagicMock()]),
        ):
            with pooled_openfga_client() as first:
                assert first.get_store_id() is None
            missing.close.assert_called_once()
            with pooled_openfga_client() as bootstrapped:
                assert bootstrapped is not first
