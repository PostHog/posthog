import json
import uuid
import base64
import dataclasses
import collections.abc

import pytest

from django.conf import settings

import temporalio.converter
from cryptography.fernet import InvalidToken
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.codec import EncryptionCodec, _load_as_bytes, _prepare_key, _resize_key

from products.batch_exports.backend.service import NoOpInputs
from products.batch_exports.backend.temporal.noop import NoOpWorkflow, noop_activity


@pytest.mark.parametrize(
    "key,size,expected",
    [
        (b"aaa", 32, b"\0" * 29 + b"aaa"),
        (b"aaa", 1, b"a"),
    ],
)
def test_resize_key_to_size(key: bytes, size: int, expected: bytes) -> None:
    result = _resize_key(key, size=size)
    assert len(result) == size
    assert result == expected


@pytest.mark.parametrize(
    "key,expected",
    [
        (b"aaa", b"\0" * 29 + b"aaa"),
        (b"a" * 32, b"a" * 32),
    ],
)
def test_resize_key(key: bytes, expected: bytes) -> None:
    result = _resize_key(key)
    assert len(result) == 32
    assert result == expected


@pytest.mark.parametrize(
    "key,expected",
    [
        (b"aaa", b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABhYWE="),
        (b"a+" * 16, b"YSthK2ErYSthK2ErYSthK2ErYSthK2ErYSthK2ErYSs="),
    ],
)
def test_prepare_key(key: bytes, expected: bytes) -> None:
    result = _prepare_key(key)
    assert result == expected
    assert base64.urlsafe_b64decode(result) == _resize_key(key)


# The presence of '?' is important as it encodes differently in standard and
# urlsafe base64 ('/' vs '_').
BYTES = b"decaf???" * 4  # 32 bytes
TEST_HEX_STRING = "hex:" + (BYTES).hex()
TEST_BASE64_URLSAFE_STRING = "base64-urlsafe:" + base64.urlsafe_b64encode(BYTES).decode()
TEST_BASE64_STRING = "base64:" + base64.b64encode(BYTES).decode()


@pytest.mark.parametrize(
    "raw,check_length,expected",
    [
        (b"a", False, b"a"),
        (TEST_HEX_STRING, True, BYTES),
        (TEST_BASE64_URLSAFE_STRING, True, BYTES),
        (TEST_BASE64_STRING, True, BYTES),
        ("any string", False, b"any string"),
    ],
)
def test_load_as_bytes(raw: str | bytes, check_length: bool, expected: bytes) -> None:
    result = _load_as_bytes(raw, check_length=check_length)
    assert result == expected


def test_codec_rejects_short_keys_when_not_debug_or_test():
    class EncryptionSettings:
        TEMPORAL_SECRET_KEY: str | bytes = b"a"
        TEMPORAL_FALLBACK_SECRET_KEYS: collections.abc.Iterable[str | bytes] = []
        TEST: bool = False
        DEBUG: bool = False

    settings = EncryptionSettings()

    with pytest.raises(ValueError):
        _ = EncryptionCodec.from_settings(settings)

    settings.TEMPORAL_FALLBACK_SECRET_KEYS = [b"b"]
    settings.TEMPORAL_SECRET_KEY = b"a" * 32

    with pytest.raises(ValueError):
        _ = EncryptionCodec.from_settings(settings)

    settings.DEBUG = True
    _ = EncryptionCodec.from_settings(settings)

    settings.DEBUG = False
    settings.TEST = True
    _ = EncryptionCodec.from_settings(settings)


class TestEncryptionSettings:
    TEMPORAL_SECRET_KEY: str | bytes = b"a" * 32
    TEMPORAL_FALLBACK_SECRET_KEYS: collections.abc.Iterable[str | bytes] = [b"b" * 32, b"c" * 32]
    TEST: bool = False
    DEBUG: bool = False


@pytest.fixture
def codec() -> EncryptionCodec:
    codec = EncryptionCodec.from_settings(TestEncryptionSettings())
    return codec


def test_encrypt_decrypt_round_trip(codec: EncryptionCodec):
    payload = b"very-secret"

    encrypted = codec.encrypt(payload)
    decrypted = codec.decrypt(encrypted)

    assert payload == decrypted


def test_encrypt_uses_main_key(codec: EncryptionCodec):
    """Assert codec encrypts using main key."""
    payload = b"very-secret"

    token = codec.encrypt(payload)

    main = codec.fernet._fernets[0]

    assert main.decrypt(token) == payload

    for fallback in codec.fernet._fernets[1:]:
        with pytest.raises(InvalidToken):
            fallback.decrypt(token)


def test_decrypt_fallsback_to_fallback_keys(codec: EncryptionCodec):
    """Assert codec can decrypt payloads encrypted with fallback keys."""
    payload = b"very-secret"

    tokens = []
    for fallback in codec.fernet._fernets[1:]:
        tokens.append(fallback.encrypt(payload))

    assert len(tokens) > 0

    for token in tokens:
        assert codec.decrypt(token) == payload


def get_history_event_payloads(event):
    """Return a history event's payloads if it has any.

    Depending on the event_type, each event has a different attribute to store the payloads (ugh).
    """
    match event.event_type:
        case EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED:
            return event.workflow_execution_started_event_attributes.input.payloads
        case EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED:
            return event.workflow_execution_completed_event_attributes.result.payloads
        case EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            return event.activity_task_scheduled_event_attributes.input.payloads
        case EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            return event.activity_task_completed_event_attributes.result.payloads
        case _:
            return None


@pytest.mark.asyncio
async def test_payloads_are_encrypted():
    """Test the payloads of a Workflow are encrypted when running with EncryptionCodec."""
    codec = EncryptionCodec.from_settings(settings=settings)
    client = await Client.connect(
        f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
        data_converter=dataclasses.replace(temporalio.converter.default(), payload_codec=codec),
    )

    workflow_id = uuid.uuid4()
    input_str = str(uuid.uuid4())

    no_op_result_str = f"OK - {input_str}"
    inputs = NoOpInputs(
        arg=input_str,
        batch_export_id="123",
        team_id=1,
        backfill_details=None,
    )

    # The no-op Workflow can only produce a limited set of results, so we'll check if the events match any of these.
    # Either it's the final result (no_op_result_str), the input to an activity (no_op_activity_input_str), or the
    # input to the workflow (inputs).
    expected_results = (
        no_op_result_str,
        {"arg": input_str, "backfill_details": None},
        dataclasses.asdict(inputs),
    )

    async with Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[NoOpWorkflow],
        activities=[noop_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ) as worker:
        handle = await client.start_workflow(
            NoOpWorkflow.run,
            inputs,
            id=f"workflow-{workflow_id}",
            task_queue=worker.task_queue,
        )

        result = await handle.result()
        assert result == no_op_result_str

        async for event in handle.fetch_history_events():
            payloads = get_history_event_payloads(event)

            if not payloads:
                continue

            payload = payloads[0]
            assert payload.metadata["encoding"] == b"binary/encrypted"

            decoded_payloads = await codec.decode([payload])
            loaded_payload = json.loads(decoded_payloads[0].data)
            assert loaded_payload in expected_results
