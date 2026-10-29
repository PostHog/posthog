from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

import grpc
from parameterized import parameterized
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
    def __init__(
        self,
        failure: tuple[grpc.StatusCode, tuple[tuple[str, str], ...]] | None = None,
        fail_once: bool = False,
    ) -> None:
        self._failure = failure
        self._fail_once = fail_once
        self.calls = 0
        self.client_names: list[str] = []
        self.time_remaining: float | None = None

    def DeletePersons(self, request, context):
        self.calls += 1
        self.client_names.extend(value for key, value in context.invocation_metadata() if key == "x-client-name")
        self.time_remaining = context.time_remaining()
        if self._failure is not None and (self.calls == 1 or not self._fail_once):
            code, trailing_metadata = self._failure
            context.set_trailing_metadata(trailing_metadata)
            context.abort(code, "injected failure")
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
    def test_lifecycle_calls_go_out_on_the_lifecycle_channel_with_client_metadata_and_deadline(self):
        service = _RecordingLifecycleService()

        with _client_for(service) as client:
            assert client.lifecycle.configured
            response = client.lifecycle.delete_persons(
                LifecycleDeletePersonsRequest(team_id=1, person_ids=[10, 20], op_id=OP_ID)
            )

        assert response.op_id == OP_ID
        assert [(r.person_id, r.outcome) for r in response.results] == [
            (10, DELETE_PERSON_OUTCOME_DELETED),
            (20, DELETE_PERSON_OUTCOME_DELETED),
        ]
        assert service.client_names == ["test-client"]
        # The lifecycle deadline, not the facade's 5 s, and above the identity server's 30 s execute timeout.
        assert service.time_remaining is not None and service.time_remaining > 30

    @parameterized.expand(
        [
            ("unavailable_is_retried", grpc.StatusCode.UNAVAILABLE, (), True, grpc.StatusCode.OK, 2, None),
            (
                "refusal_trailer_reaches_the_caller_on_the_first_call",
                grpc.StatusCode.FAILED_PRECONDITION,
                (("x-semantic-refusal", "op_id_reused"),),
                False,
                grpc.StatusCode.FAILED_PRECONDITION,
                1,
                "op_id_reused",
            ),
        ]
    )
    def test_retry_decision_on_the_lifecycle_channel(
        self,
        _name: str,
        failure_code: grpc.StatusCode,
        trailing_metadata: tuple[tuple[str, str], ...],
        fail_once: bool,
        expected_code: grpc.StatusCode,
        expected_calls: int,
        expected_reason: str | None,
    ):
        service = _RecordingLifecycleService(failure=(failure_code, trailing_metadata), fail_once=fail_once)

        with _client_for(service) as client:
            try:
                client.lifecycle.delete_persons(LifecycleDeletePersonsRequest(team_id=1, person_ids=[10], op_id=OP_ID))
                code, reason = grpc.StatusCode.OK, None
            except grpc.RpcError as exc:
                code, reason = exc.code(), semantic_refusal_reason(exc)

        assert (code, reason, service.calls) == (expected_code, expected_reason, expected_calls)

    def test_without_a_lifecycle_address_the_method_refuses_instead_of_dialling_the_facade(self):
        client = PersonHogClient("localhost:1", client_name="test-client")
        try:
            assert not client.lifecycle.configured
            with pytest.raises(PersonHogLifecycleUnavailable):
                client.lifecycle.delete_persons(LifecycleDeletePersonsRequest(team_id=1, person_ids=[10], op_id=OP_ID))
        finally:
            client.close()
