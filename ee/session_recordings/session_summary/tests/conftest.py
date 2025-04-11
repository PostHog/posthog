from typing import Any
import pytest
from datetime import datetime
from openai.types.chat.chat_completion import ChatCompletion, Choice, ChatCompletionMessage


@pytest.fixture
def mock_valid_llm_yaml_response() -> str:
    return """```yaml
summary: User logged in and created a new project
key_events:
  - description: User clicked login button
    error: false
    tags:
      where: ["login page"]
      what: ["authentication"]
    importance: 0.8
    event_id: abc123
  - description: User created new project
    error: false
    tags:
      where: ["dashboard"]
      what: ["project creation"]
    importance: 0.9
    event_id: def456
```"""


@pytest.fixture
def mock_chat_completion(mock_valid_llm_yaml_response: str) -> ChatCompletion:
    return ChatCompletion(
        id="test_id",
        model="test_model",
        object="chat.completion",
        created=int(datetime.now().timestamp()),
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(
                    content=mock_valid_llm_yaml_response,
                    role="assistant",
                ),
            )
        ],
    )


@pytest.fixture
def mock_raw_metadata() -> dict[str, Any]:
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        # Anonymized distinct_id for testing
        "distinct_id": "EheLkWe3eZBtiru9xSJgq2SNWoD8YHQnKu0FWkMDZMU",
        "viewed": True,
        "viewers": [],
        "recording_duration": 5323,
        "active_seconds": 1947,
        "inactive_seconds": 3375,
        "start_time": "2025-04-01T11:13:33.315000Z",
        "end_time": "2025-04-01T12:42:16.671000Z",
        "click_count": 679,
        "keypress_count": 668,
        "mouse_activity_count": 6629,
        "console_log_count": 4,
        "console_warn_count": 144,
        "console_error_count": 114,
        "start_url": "https://us.example.com/project/11111/insights/aAaAAAaA",
        "storage": "object_storage",
        "snapshot_source": "web",
        "ongoing": None,
        "activity_score": None,
    }


@pytest.fixture
def mock_raw_events() -> list[list[Any]]:
    return [
        [
            "client_request_failure",
            datetime(2025, 3, 31, 18, 40, 39, 302000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            None,
        ],
        [
            "$pageview",
            datetime(2025, 3, 31, 18, 40, 39, 200000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            None,
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 40, 43, 645000),
            "",
            ["Log in"],
            ["button", "form"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            "click",
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 40, 43, 647000),
            "",
            [],
            ["form"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            "submit",
        ],
        [
            "$web_vitals",
            datetime(2025, 3, 31, 18, 40, 44, 251000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            None,
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 40, 58, 699000),
            "/signup",
            ["Create an account"],
            ["a"],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/login?next=/",
            "click",
        ],
        [
            "$pageview",
            datetime(2025, 3, 31, 18, 40, 58, 710000),
            "",
            [],
            [],
            "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "http://localhost:8010/signup",
            None,
        ],
        [
            "$autocapture",
            datetime(2025, 3, 31, 18, 41, 5, 459000),
            "",
            ["Continue"],
            ["button", "form"],
            "0235ed82-1519-7595-9221-8bb8ddb1fdc4",
            "http://localhost:8010/signup",
            "click",
        ],
    ]
