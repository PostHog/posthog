import importlib

import pytest

from posthog.schema import FunnelsQuery

from posthog.schema_migrations import LATEST_VERSIONS
from posthog.schema_migrations.upgrade import upgrade

SERIES = [{"kind": "EventsNode", "event": "$pageview"}, {"kind": "EventsNode", "event": "sign_up"}]
FORMULA_NODES = [{"formula": "(A/B)*100", "custom_name": None}]


def _get_migration():
    migration_module = importlib.import_module("posthog.schema_migrations.0005_funnels_filter_drop_trends_formulas")
    return migration_module.Migration()


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            {"kind": "FunnelsQuery", "funnelsFilter": {"funnelVizType": "steps", "formulaNodes": FORMULA_NODES}},
            {"kind": "FunnelsQuery", "funnelsFilter": {"funnelVizType": "steps"}},
        ),
        (
            {"kind": "FunnelsQuery", "funnelsFilter": {"formula": "A+B", "formulas": ["A+B"], "formulaNodes": []}},
            {"kind": "FunnelsQuery", "funnelsFilter": {}},
        ),
        (
            {"kind": "FunnelsQuery", "funnelsFilter": {"funnelVizType": "steps"}},
            {"kind": "FunnelsQuery", "funnelsFilter": {"funnelVizType": "steps"}},
        ),
        ({"kind": "FunnelsQuery", "funnelsFilter": None}, {"kind": "FunnelsQuery", "funnelsFilter": None}),
        ({"kind": "FunnelsQuery"}, {"kind": "FunnelsQuery"}),
        (
            {"kind": "FunnelsQuery", "trendsFilter": {"formulaNodes": FORMULA_NODES}},
            {"kind": "FunnelsQuery", "trendsFilter": {"formulaNodes": FORMULA_NODES}},
        ),
    ],
)
def test_transform(query, expected):
    assert _get_migration().transform(query) == expected


def test_upgraded_saved_funnel_validates():
    query = {
        "kind": "FunnelsQuery",
        "version": 2,
        "series": SERIES,
        "funnelsFilter": {"funnelVizType": "steps", "formulaNodes": FORMULA_NODES},
    }

    upgraded = upgrade(query)

    assert upgraded["version"] == LATEST_VERSIONS["FunnelsQuery"]
    FunnelsQuery.model_validate(upgraded)
