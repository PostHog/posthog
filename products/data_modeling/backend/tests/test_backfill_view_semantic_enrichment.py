from io import StringIO
from typing import Any

import pytest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Organization, Team

from products.data_modeling.backend.logic.enrich_view_semantics import compute_enrichment_hash
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

pytestmark = pytest.mark.django_db

COMMAND = "backfill_view_semantic_enrichment"
DISPATCH = (
    "products.data_modeling.backend.management.commands.backfill_view_semantic_enrichment.dispatch_view_enrichment"
)


def _team() -> Team:
    return Team.objects.create(organization=Organization.objects.create(name="org"), name="t")


def _columns(*names: str) -> dict[str, Any]:
    return {name: {"clickhouse": "String", "hogql": "StringDatabaseField"} for name in names}


def _saved_query(team: Team, **extra: Any) -> DataWarehouseSavedQuery:
    return DataWarehouseSavedQuery.objects.create(
        team=team,
        name=extra.pop("name", "my_view"),
        query={"query": extra.pop("query", "SELECT amount FROM events")},
        columns=extra.pop("columns", _columns("amount")),
        **extra,
    )


def _run(**options: Any) -> tuple[Any, str]:
    with patch(DISPATCH) as dispatch:
        out = StringIO()
        call_command(COMMAND, sleep=0, stdout=out, **options)
    return dispatch, out.getvalue()


class TestBackfillViewSemanticEnrichment:
    def test_live_run_dispatches_eligible_view(self):
        team = _team()
        sq = _saved_query(team)

        dispatch, _ = _run(team_ids=[team.id], live_run=True)

        dispatch.assert_called_once_with(team.id, str(sq.id))

    def test_dry_run_is_default_and_dispatches_nothing(self):
        team = _team()
        _saved_query(team)

        dispatch, output = _run(team_ids=[team.id])

        dispatch.assert_not_called()
        assert "would dispatch 1" in output

    def test_team_ids_excludes_other_teams(self):
        targeted, other = _team(), _team()
        sq = _saved_query(targeted)
        _saved_query(other)

        dispatch, _ = _run(team_ids=[targeted.id], live_run=True)

        dispatch.assert_called_once_with(targeted.id, str(sq.id))

    def test_all_covers_every_team(self):
        team_a, team_b = _team(), _team()
        _saved_query(team_a)
        _saved_query(team_b)

        dispatch, _ = _run(all=True, live_run=True)

        assert dispatch.call_count == 2

    def test_limit_caps_dispatches(self):
        team = _team()
        for i in range(3):
            _saved_query(team, name=f"view_{i}")

        dispatch, output = _run(all=True, live_run=True, limit=2)

        assert dispatch.call_count == 2
        assert "--limit 2" in output

    @parameterized.expand(
        [
            ("deleted", {"deleted": True}),
            ("is_test", {"is_test": True}),
            ("empty_columns", {"columns": {}}),
            ("already_enriched", {"enriched": True}),
            ("managed_viewset", {"managed": True}),
        ]
    )
    def test_skips_gated_or_ineligible_views(self, _name, mods):
        team = _team()
        if mods.pop("managed", False):
            mods["managed_viewset"] = DataWarehouseManagedViewSet.objects.create(
                team=team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
            )
        enriched = mods.pop("enriched", False)
        sq = _saved_query(team, **mods)
        if enriched:
            DataWarehouseSavedQuery.objects.filter(id=sq.id).update(
                semantic_enrichment_hash=compute_enrichment_hash(sq)
            )

        dispatch, _ = _run(team_ids=[team.id], live_run=True)

        dispatch.assert_not_called()
