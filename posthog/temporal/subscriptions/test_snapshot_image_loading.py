import pytest
from unittest.mock import patch

from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.temporal.subscriptions.snapshot_activities import MAX_SUMMARY_IMAGES, _load_insight_images

pytestmark = pytest.mark.django_db


def _create_png_asset(
    team,
    insight,
    *,
    content: bytes | None = None,
    content_location: str | None = None,
    export_format: str = ExportedAsset.ExportFormat.PNG,
) -> ExportedAsset:
    return ExportedAsset.objects.create(
        team=team,
        insight=insight,
        export_format=export_format,
        content=content,
        content_location=content_location,
    )


def test_returns_empty_when_no_asset_ids(team, user):
    assert _load_insight_images([]) == {}


def test_loads_bytes_from_content_field(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=b"the-png-bytes")

    result = _load_insight_images([asset.id])

    assert result == {insight.id: b"the-png-bytes"}


def test_loads_bytes_from_object_storage_when_content_empty(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location="s3://path/to/png")

    with patch(
        "posthog.temporal.subscriptions.snapshot_activities.object_storage.read_bytes",
        return_value=b"from-s3",
    ):
        result = _load_insight_images([asset.id])

    assert result == {insight.id: b"from-s3"}


def test_skips_when_storage_raises(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location="s3://path")

    with patch(
        "posthog.temporal.subscriptions.snapshot_activities.object_storage.read_bytes",
        side_effect=RuntimeError("boom"),
    ):
        result = _load_insight_images([asset.id])

    assert result == {}


def test_skips_asset_without_insight_id(team, user):
    ExportedAsset.objects.create(team=team, insight=None, export_format=ExportedAsset.ExportFormat.PNG, content=b"png")
    asset = ExportedAsset.objects.first()

    result = _load_insight_images([asset.id])

    assert result == {}


def test_skips_asset_with_no_content_or_location(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location=None)

    result = _load_insight_images([asset.id])

    assert result == {}


def test_skips_non_png_exports(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=b"csv-bytes", export_format=ExportedAsset.ExportFormat.CSV)

    result = _load_insight_images([asset.id])

    assert result == {}


def test_skips_assets_larger_than_cap(team, user):
    from posthog.temporal.subscriptions import snapshot_activities

    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    with patch.object(snapshot_activities, "MAX_IMAGE_BYTES", 4):
        asset = _create_png_asset(team, insight, content=b"too-long-content")
        result = _load_insight_images([asset.id])

    assert result == {}


def test_caps_total_images_at_max(team, user):
    asset_ids: list[int] = []
    expected_first_insight_id: int | None = None
    for i in range(MAX_SUMMARY_IMAGES + 2):
        insight = Insight.objects.create(team=team, name=f"pv-{i}", created_by=user)
        if expected_first_insight_id is None:
            expected_first_insight_id = insight.id
        asset = _create_png_asset(team, insight, content=b"png")
        asset_ids.append(asset.id)

    result = _load_insight_images(asset_ids)

    assert len(result) == MAX_SUMMARY_IMAGES
