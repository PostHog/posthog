from uuid import UUID, uuid4

from posthog.temporal.export_recording.types import ExportContext, ExportRecordingInput, RedisConfig


def test_redis_config_defaults():
    config = RedisConfig()
    assert config.redis_url is None
    assert config.redis_ttl == 3600 * 6


def test_redis_config_custom_values():
    config = RedisConfig(redis_url="redis://custom-redis:6380", redis_ttl=7200)
    assert config.redis_url == "redis://custom-redis:6380"
    assert config.redis_ttl == 7200


def test_export_recording_input_creation():
    recording_id = UUID("01938a67-1234-7000-8000-000000000001")
    input = ExportRecordingInput(exported_recording_id=recording_id)
    assert input.exported_recording_id == recording_id
    assert input.redis_config.redis_url is None


def test_export_recording_input_with_custom_redis_config():
    recording_id = UUID("01938a67-1234-7000-8000-000000000001")
    redis_config = RedisConfig(redis_url="redis://custom-host:6380")
    input = ExportRecordingInput(exported_recording_id=recording_id, redis_config=redis_config)
    assert input.exported_recording_id == recording_id
    assert input.redis_config.redis_url == "redis://custom-host:6380"


def test_export_context_creation():
    export_id = uuid4()
    recording_id = UUID("01938a67-5678-7000-8000-000000000002")
    redis_config = RedisConfig()
    context = ExportContext(
        export_id=export_id,
        exported_recording_id=recording_id,
        session_id="test-session-id",
        team_id=67890,
        redis_config=redis_config,
    )
    assert context.export_id == export_id
    assert context.exported_recording_id == recording_id
    assert context.session_id == "test-session-id"
    assert context.team_id == 67890
    assert context.redis_config == redis_config


def test_export_context_mutability():
    export_id = uuid4()
    recording_id = UUID("01938a67-9abc-7000-8000-000000000003")
    redis_config = RedisConfig()
    context = ExportContext(
        export_id=export_id,
        exported_recording_id=recording_id,
        session_id="original-id",
        team_id=123,
        redis_config=redis_config,
    )
    context.session_id = "new-id"
    assert context.session_id == "new-id"


def test_export_recording_input_mutability():
    recording_id = UUID("01938a67-def0-7000-8000-000000000004")
    new_recording_id = UUID("01938a67-1111-7000-8000-000000000005")
    input = ExportRecordingInput(exported_recording_id=recording_id)
    input.exported_recording_id = new_recording_id
    assert input.exported_recording_id == new_recording_id
