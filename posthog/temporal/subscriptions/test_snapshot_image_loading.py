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
    assert _load_insight_images([], team.id) == {}


def test_loads_bytes_from_content_field(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=b"the-png-bytes")

    result = _load_insight_images([asset.id], team.id)

    assert result == {insight.id: b"the-png-bytes"}


def test_loads_bytes_from_object_storage_when_content_empty(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location="s3://path/to/png")

    with patch(
        "posthog.temporal.subscriptions.snapshot_activities.object_storage.read_bytes",
        return_value=b"from-s3",
    ):
        result = _load_insight_images([asset.id], team.id)

    assert result == {insight.id: b"from-s3"}


def test_skips_when_storage_raises(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location="s3://path")

    with patch(
        "posthog.temporal.subscriptions.snapshot_activities.object_storage.read_bytes",
        side_effect=RuntimeError("boom"),
    ):
        result = _load_insight_images([asset.id], team.id)

    assert result == {}


def test_skips_asset_without_insight_id(team, user):
    ExportedAsset.objects.create(team=team, insight=None, export_format=ExportedAsset.ExportFormat.PNG, content=b"png")
    asset = ExportedAsset.objects.first()

    result = _load_insight_images([asset.id], team.id)

    assert result == {}


def test_skips_asset_with_no_content_or_location(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location=None)

    result = _load_insight_images([asset.id], team.id)

    assert result == {}


def test_skips_non_png_exports(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=b"csv-bytes", export_format=ExportedAsset.ExportFormat.CSV)

    result = _load_insight_images([asset.id], team.id)

    assert result == {}


def test_skips_assets_larger_than_cap(team, user):
    from posthog.temporal.subscriptions import snapshot_activities

    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    with patch.object(snapshot_activities, "MAX_IMAGE_BYTES", 4):
        asset = _create_png_asset(team, insight, content=b"too-long-content")
        result = _load_insight_images([asset.id], team.id)

    assert result == {}


def test_caps_total_images_at_max_and_keeps_input_order(team, user):
    asset_ids: list[int] = []
    insight_ids_in_order: list[int] = []
    for i in range(MAX_SUMMARY_IMAGES + 2):
        insight = Insight.objects.create(team=team, name=f"pv-{i}", created_by=user)
        insight_ids_in_order.append(insight.id)
        asset = _create_png_asset(team, insight, content=b"png")
        asset_ids.append(asset.id)

    result = _load_insight_images(asset_ids, team.id)

    assert len(result) == MAX_SUMMARY_IMAGES
    assert list(result.keys()) == insight_ids_in_order[:MAX_SUMMARY_IMAGES]


def test_preserves_order_when_asset_ids_are_not_sequential(team, user):
    insights = [Insight.objects.create(team=team, name=f"pv-{i}", created_by=user) for i in range(3)]
    assets = [_create_png_asset(team, insight, content=f"png-{i}".encode()) for i, insight in enumerate(insights)]
    shuffled = [assets[2].id, assets[0].id, assets[1].id]

    result = _load_insight_images(shuffled, team.id)

    assert list(result.keys()) == [insights[2].id, insights[0].id, insights[1].id]


def test_scopes_to_team_and_drops_other_teams_assets(team, user):
    from posthog.models import Team

    other_team = Team.objects.create(organization=team.organization, name="other")
    own_insight = Insight.objects.create(team=team, name="own", created_by=user)
    own_asset = _create_png_asset(team, own_insight, content=b"own-png")
    other_insight = Insight.objects.create(team=other_team, name="other", created_by=user)
    other_asset = ExportedAsset.objects.create(
        team=other_team,
        insight=other_insight,
        export_format=ExportedAsset.ExportFormat.PNG,
        content=b"other-png",
    )

    result = _load_insight_images([own_asset.id, other_asset.id], team.id)

    assert result == {own_insight.id: b"own-png"}


def test_skips_when_aggregate_bytes_exceeded(team, user):
    from posthog.temporal.subscriptions import snapshot_activities

    insights = [Insight.objects.create(team=team, name=f"pv-{i}", created_by=user) for i in range(3)]
    assets = [_create_png_asset(team, insight, content=b"XXXX") for insight in insights]

    with patch.object(snapshot_activities, "MAX_TOTAL_IMAGE_BYTES", 9):
        result = _load_insight_images([a.id for a in assets], team.id)

    assert list(result.keys()) == [insights[0].id, insights[1].id]
