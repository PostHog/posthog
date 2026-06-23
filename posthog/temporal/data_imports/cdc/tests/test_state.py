import uuid

import pytest

from posthog.temporal.data_imports.cdc.state import update_cdc_state

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

pytestmark = pytest.mark.django_db


def _source(team):
    return ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="Postgres",
    )


def test_update_cdc_state_initializes_from_none(team):
    source = _source(team)
    assert source.cdc_state is None

    returned = update_cdc_state(source.id, lag_bytes=10)

    source.refresh_from_db()
    assert source.cdc_state == {"lag_bytes": 10}
    assert returned == {"lag_bytes": 10}  # type: ignore[unreachable]


def test_update_cdc_state_merges_keys(team):
    source = _source(team)
    update_cdc_state(source.id, paused=True)

    update_cdc_state(source.id, lag_bytes=10)

    source.refresh_from_db()
    assert source.cdc_state == {"paused": True, "lag_bytes": 10}


def test_update_cdc_state_overwrites_existing_key(team):
    source = _source(team)
    update_cdc_state(source.id, lag_bytes=10)

    update_cdc_state(source.id, lag_bytes=20)

    source.refresh_from_db()
    assert source.cdc_state["lag_bytes"] == 20
