from collections.abc import Collection
from typing import TYPE_CHECKING

from products.data_modeling.backend.logic.demand import ModelDemand

if TYPE_CHECKING:
    from posthog.models import Team


def record_model_demand(team: "Team", saved_query_ids: Collection[str]) -> None:
    if ModelDemand.enabled(team):
        ModelDemand.record(team.pk, saved_query_ids)
