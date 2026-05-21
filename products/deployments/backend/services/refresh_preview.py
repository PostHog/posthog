"""Re-capture the preview screenshot for a deployment.

Best-effort: a failure surfaces as a `preview_capture_failed` DeploymentEvent
row but the call still returns a 200 to the caller. The frontend re-polls
the detail endpoint after triggering this and reads the new
`preview_image_url` field.
"""

from __future__ import annotations

from ..adapters import ScreenshotAdapter, get_screenshot_adapter
from ..models import Deployment, DeploymentEvent


def execute(*, deployment_id: str, team_id: int, screenshot: ScreenshotAdapter | None = None) -> Deployment:
    deployment = Deployment.objects.get(pk=deployment_id, team_id=team_id)
    if not deployment.deployment_url:
        DeploymentEvent.objects.create(
            deployment_id=deployment.pk,
            team_id=team_id,
            event_type="preview_capture_failed",
            payload={"reason": "no_deployment_url"},
        )
        return deployment

    adapter = screenshot or get_screenshot_adapter()
    image_url = adapter.capture(url=deployment.deployment_url)
    if image_url:
        Deployment.objects.filter(pk=deployment.pk).update(preview_image_url=image_url)
        DeploymentEvent.objects.create(
            deployment_id=deployment.pk,
            team_id=team_id,
            event_type="preview_captured",
            payload={"url": image_url},
        )
        deployment.refresh_from_db(fields=["preview_image_url"])
    else:
        DeploymentEvent.objects.create(
            deployment_id=deployment.pk,
            team_id=team_id,
            event_type="preview_capture_failed",
            payload={"deployment_url": deployment.deployment_url},
        )
    return deployment
