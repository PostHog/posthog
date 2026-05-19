from contextlib import contextmanager

import pytest
from unittest.mock import patch

from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.temporal.subscriptions.snapshot_activities import (
    MAX_SUMMARY_IMAGES,
    SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED,
    _load_insight_images,
)

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


@contextmanager
def _no_insight_id_scenario(team, user):
    asset = ExportedAsset.objects.create(
        team=team, insight=None, export_format=ExportedAsset.ExportFormat.PNG, content=b"png"
    )
    yield asset.id


@contextmanager
def _no_content_or_location_scenario(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location=None)
    yield asset.id


@contextmanager
def _non_png_export_scenario(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=b"csv-bytes", export_format=ExportedAsset.ExportFormat.CSV)
    yield asset.id


@contextmanager
def _over_image_size_cap_scenario(team, user):
    from posthog.temporal.subscriptions import snapshot_activities

    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    with patch.object(snapshot_activities, "MAX_IMAGE_BYTES", 4):
        asset = _create_png_asset(team, insight, content=b"too-long-content")
        yield asset.id


@contextmanager
def _storage_error_scenario(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    asset = _create_png_asset(team, insight, content=None, content_location="s3://path")
    with patch(
        "posthog.temporal.subscriptions.snapshot_activities.object_storage.read_bytes",
        side_effect=RuntimeError("boom"),
    ):
        yield asset.id


@contextmanager
def _missing_from_db_scenario(team, user):
    # asset_id that doesn't exist — e.g. deleted between workflow export and snapshot activity
    yield 999_999_999


@pytest.mark.parametrize(
    "reason,scenario",
    [
        ("no_insight_id", _no_insight_id_scenario),
        ("no_content_or_location", _no_content_or_location_scenario),
        ("non_png_export", _non_png_export_scenario),
        ("over_image_size_cap", _over_image_size_cap_scenario),
        ("storage_error", _storage_error_scenario),
        ("missing_from_db", _missing_from_db_scenario),
    ],
)
def test_returns_empty_for_unloadable_asset(team, user, reason, scenario):
    with scenario(team, user) as asset_id:
        result = _load_insight_images([asset_id], team.id)

    assert result == {}


def test_skips_duplicate_insight_with_counter(team, user):
    insight = Insight.objects.create(team=team, name="pv", created_by=user)
    first = _create_png_asset(team, insight, content=b"first-png")
    duplicate = _create_png_asset(team, insight, content=b"second-png")

    before = SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="duplicate_insight")._value.get()

    result = _load_insight_images([first.id, duplicate.id], team.id)

    after = SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="duplicate_insight")._value.get()
    assert result == {insight.id: b"first-png"}
    assert after - before == 1


def test_missing_asset_increments_not_found_counter(team, user):
    before = SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="not_found")._value.get()

    result = _load_insight_images([999_999_999], team.id)

    after = SUBSCRIPTION_SUMMARY_IMAGE_SKIPPED.labels(reason="not_found")._value.get()
    assert result == {}
    assert after - before == 1


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
