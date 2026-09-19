import io
import base64
import binascii
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

from posthog.storage import object_storage

if TYPE_CHECKING:
    from products.canvas.backend.models import Canvas
    from products.tasks.backend.facade.canvas_tasks import TaskScreenshot

MAX_SCREENSHOT_BYTES = 1024 * 1024
MAX_SCREENSHOTS = 6
MAX_SCREENSHOT_PIXELS = 16_000_000


class ScreenshotUploadSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4 * ((MAX_SCREENSHOT_BYTES + 2) // 3), trim_whitespace=False)

    def validate_content(self, value: str) -> bytes:
        try:
            content = base64.b64decode(value, validate=True)
            if not content or len(content) > MAX_SCREENSHOT_BYTES:
                raise ValueError
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ("PNG", "JPEG", "WEBP") or image.width * image.height > MAX_SCREENSHOT_PIXELS:
                    raise ValueError
                image.verify()
        except (ValueError, binascii.Error, OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError):
            raise serializers.ValidationError("Select a PNG, JPEG, or WebP image under 1 MB and 16 megapixels.")
        return content


class ScreenshotReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()


def screenshot_path(team_id: int, user_id: int, canvas_id: UUID, screenshot_id: UUID) -> str:
    return f"canvas/screenshots/team_{team_id}/user_{user_id}/canvas_{canvas_id}/{screenshot_id}"


def read_screenshot(team_id: int, user_id: int, canvas_id: UUID, screenshot_id: UUID) -> bytes:
    content = object_storage.read_bytes(screenshot_path(team_id, user_id, canvas_id, screenshot_id), missing_ok=True)
    if not content:
        raise ValueError("Screenshot not found. Remove it and attach it again.")
    return content


def upload_screenshot(team_id: int, user_id: int, canvas: "Canvas", payload: dict[str, Any]) -> dict[str, Any]:
    screenshot_id = uuid4()
    object_storage.write(screenshot_path(team_id, user_id, canvas.id, screenshot_id), payload["content"])
    return {"id": str(screenshot_id)}


def preview_screenshot(team_id: int, user_id: int, canvas: "Canvas", payload: dict[str, Any]) -> dict[str, Any]:
    content = read_screenshot(team_id, user_id, canvas.id, payload["id"])
    with Image.open(io.BytesIO(content)) as image:
        content_type = Image.MIME[image.format or ""]
    return {"content": base64.b64encode(content).decode("ascii"), "content_type": content_type}


def load_task_screenshots(
    team_id: int, user_id: int, canvas_id: UUID, screenshot_ids: list[UUID]
) -> list["TaskScreenshot"]:
    screenshots = []
    for index, screenshot_id in enumerate(screenshot_ids):
        content = read_screenshot(team_id, user_id, canvas_id, screenshot_id)
        with Image.open(io.BytesIO(content)) as image:
            content_type = Image.MIME[image.format or ""]
            extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[image.format or ""]
        screenshots.append((f"screenshot-{index + 1}.{extension}", content, content_type))
    return screenshots
