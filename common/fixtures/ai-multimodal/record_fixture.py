"""Regenerates the shared multimodal AI fixture from a real provider call.

Run this by hand when the SDK's event shape changes. It makes a genuine OpenAI
request with a real screenshot so the recorded payload matches what production
emits; CI only ever replays the recorded result.

    OPENAI_API_KEY=sk-... python common/fixtures/ai-multimodal/record_fixture.py

The event is intercepted via the SDK's `before_send` hook and never sent anywhere.
"""

import os
import json
import base64
import pathlib

from posthog import Posthog
from posthog.ai.openai import OpenAI

HERE = pathlib.Path(__file__).parent
SCREENSHOT = HERE / "screenshot.png"
FIXTURE = HERE / "generation-event.json"


def main() -> None:
    image_b64 = base64.b64encode(SCREENSHOT.read_bytes()).decode("ascii")

    captured: dict = {}

    def record(event: dict) -> None:
        # Returning None drops the event, so recording never sends anything.
        captured.update(event)
        return None

    # _enable_multimodal_capture is required twice over: without it the SDK's
    # sanitizer replaces the base64 with "[base64 image redacted]", and it is
    # also what routes the event onto the AI lane.
    ph = Posthog(
        "phc_recording_only",
        host="http://localhost:8010",
        _enable_multimodal_capture=True,
        before_send=record,
        sync_mode=True,
    )
    client = OpenAI(posthog_client=ph, api_key=os.environ["OPENAI_API_KEY"])

    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this screenshot in one sentence."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }
        ],
    )
    ph.flush()

    if not captured:
        raise SystemExit("before_send never fired — no event was recorded")

    properties = captured["properties"]
    encoded = json.dumps(properties["$ai_input"])
    if "[base64 image redacted]" in encoded:
        raise SystemExit("image was redacted — _enable_multimodal_capture did not take effect")
    if len(image_b64) <= 20480:
        raise SystemExit(
            f"screenshot is too small ({len(image_b64)} base64 chars); "
            "it must exceed AI_BLOB_OFFLOAD_MIN_BASE64_LENGTH (20480) or ingestion will not offload it"
        )

    FIXTURE.write_text(
        json.dumps(
            {
                "event": captured["event"],
                "distinct_id": captured["distinct_id"],
                "properties": properties,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"wrote {FIXTURE} ({len(image_b64)} base64 chars of image)")  # noqa: T201


if __name__ == "__main__":
    main()
