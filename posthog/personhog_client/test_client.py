from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

import grpc
from personhog.lifecycle.v1.lifecycle_pb2_grpc import (
    PersonHogLifecycleServicer,
    add_PersonHogLifecycleServicer_to_server,
)

from posthog.personhog_client.client import PersonHogClient, PersonHogLifecycleUnavailable
from posthog.personhog_client.interceptor import semantic_refusal_reason
from posthog.personhog_client.proto import (
    DELETE_PERSON_OUTCOME_DELETED,
    LifecycleDeletePersonsRequest,
    LifecycleDeletePersonsResponse,
)

OP_ID = "6f1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b"


class _RecordingLifecycleService(PersonHogLifecycleServicer):
    def __init__(self, refusal: tuple[grpc.StatusCode, tuple[tuple[str, str], ...]] | None = None) -> None:
        self._refusal = refusal
        self.calls = 0
        self.client_names: list[str] = []

    def DeletePersons(self, request, context):
        self.calls += 1
        self.client_names.extend(value for key, value in context.invocation_metadata() if key == "x-client-name")
        if self._refusal is not None:
            code, trailing_metadata = self._refusal
            context.set_trailing_metadata(trailing_metadata)
            context.abort(code, "injected refusal")
        response = LifecycleDeletePersonsResponse(op_id=request.op_id)
        for person_id in request.person_ids:
            response.results.add(person_id=person_id, outcome=DELETE_PERSON_OUTCOME_DELETED)
        return response


@contextmanager
def _client_for(service: PersonHogLifecycleServicer) -> Iterator[PersonHogClient]:
    with ThreadPoolExecutor(max_workers=1) as pool:
        server = grpc.server(pool)
        add_PersonHogLifecycleServicer_to_server(service, server)
        port = server.add_insecure_port("localhost:0")
        server.start()
        # The facade address is never dialled here: gRPC channels connect on first use.
        client = PersonHogClient(
            "localhost:1",
            client_name="test-client",
            lifecycle_addr=f"localhost:{port}",
            initial_backoff_ms=1,
            max_backoff_ms=1,
        )
        try:
            yield client
        finally:
            client.close()
            server.stop(None)


class TestLifecycleChannel:
    def test_lifecycle_calls_go_out_on_the_lifecycle_channel_with_client_metadata(self):
        service = _RecordingLifecycleService()

        with _client_for(service) as client:
            assert client.lifecycle_configured
            response = client.delete_persons_lifecycle(
                LifecycleDeletePersonsRequest(team_id=1, person_ids=[10, 20], op_id=OP_ID)
            )

        assert response.op_id == OP_ID
        assert [(r.person_id, r.outcome) for r in response.results] == [
            (10, DELETE_PERSON_OUTCOME_DELETED),
            (20, DELETE_PERSON_OUTCOME_DELETED),
        ]
        assert service.client_names == ["test-client"]

    def test_semantic_refusal_is_not_retried_and_exposes_its_reason(self):
        service = _RecordingLifecycleService(
            refusal=(grpc.StatusCode.FAILED_PRECONDITION, (("x-semantic-refusal", "op_id_reused"),))
        )

        with _client_for(service) as client:
            with pytest.raises(grpc.RpcError) as raised:
                client.delete_persons_lifecycle(LifecycleDeletePersonsRequest(team_id=1, person_ids=[10], op_id=OP_ID))

        assert raised.value.code() == grpc.StatusCode.FAILED_PRECONDITION
        assert semantic_refusal_reason(raised.value) == "op_id_reused"
        assert service.calls == 1

    def test_without_a_lifecycle_address_the_method_refuses_instead_of_dialling_the_facade(self):
        client = PersonHogClient("localhost:1", client_name="test-client")
        try:
            assert not client.lifecycle_configured
            with pytest.raises(PersonHogLifecycleUnavailable):
                client.delete_persons_lifecycle(LifecycleDeletePersonsRequest(team_id=1, person_ids=[10], op_id=OP_ID))
        finally:
            client.close()
