"""End-to-end coverage of the blessed multimodal AI ingestion path.

Paired with products/ai_observability/frontend/e2e/multimodal-trace.spec.ts, which covers
rendering. Only the two together are end-to-end, so changes to the fixture or the assertions
here need the matching change there.
"""

import re
import json
import time
import uuid
import base64
import hashlib
import logging
import pathlib
from urllib.parse import unquote

import pytest

logger = logging.getLogger(__name__)

FIXTURE_DIR = pathlib.Path(__file__).parents[2] / "fixtures" / "ai-multimodal"
POINTER_RE = re.compile(r"phaiblob://v1/sha256/(?P<hash>[0-9a-f]{64})\?mime=(?P<mime>[^&]+)&size=(?P<size>\d+)")


@pytest.fixture(scope="module")
def recorded_event() -> dict:
    return json.loads((FIXTURE_DIR / "generation-event.json").read_text())


@pytest.fixture(scope="module")
def screenshot_bytes() -> bytes:
    return (FIXTURE_DIR / "screenshot.png").read_bytes()


class TestMultimodalBlessedPath:
    def test_inline_image_is_offloaded_to_a_blob_pointer(self, shared_org_project, recorded_event, screenshot_bytes):
        client = shared_org_project["client"]
        project_id = shared_org_project["project_id"]

        trace_id = f"e2e-multimodal-{uuid.uuid4()}"
        distinct_id = f"e2e-multimodal-user-{uuid.uuid4()}"

        client.capture_ai_event(
            api_key=shared_org_project["api_key"],
            event=recorded_event["event"],
            distinct_id=distinct_id,
            properties={**recorded_event["properties"], "$ai_trace_id": trace_id},
        )

        event = client.wait_for_event(project_id, recorded_event["event"], distinct_id)
        assert event is not None, f"$ai_generation for distinct_id={distinct_id} never arrived in events"

        stored_input = None
        for _ in range(30):
            stored_input = client.read_ai_events_input(trace_id)
            if stored_input:
                break
            time.sleep(2)

        assert stored_input is not None, f"no ai_events row for trace_id={trace_id} after 60s"

        assert "data:image/png;base64," not in stored_input, "image was left inline, offload did not run"

        match = POINTER_RE.search(stored_input)
        assert match, f"no phaiblob:// pointer in stored input: {stored_input[:300]}"

        expected_hash = hashlib.sha256(screenshot_bytes).hexdigest()
        assert match.group("hash") == expected_hash
        assert unquote(match.group("mime")) == "image/png"
        assert int(match.group("size")) == len(screenshot_bytes)

        blob = client.read_ai_blob(team_id=project_id, hash=expected_hash)
        assert hashlib.sha256(blob).hexdigest() == expected_hash

    def test_recorded_fixture_would_trigger_offload(self, recorded_event):
        encoded = json.dumps(recorded_event["properties"]["$ai_input"])
        data_url = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", encoded)
        assert data_url, "fixture has no inline base64 image"
        assert len(data_url.group(1)) > 20480, (
            f"fixture image is {len(data_url.group(1))} base64 chars, at or under "
            "AI_BLOB_OFFLOAD_MIN_BASE64_LENGTH (20480), so ingestion would not offload it"
        )
        assert base64.b64decode(data_url.group(1)), "inline image is not valid base64"
