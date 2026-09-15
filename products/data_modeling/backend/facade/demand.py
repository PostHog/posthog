from collections.abc import Collection

from products.data_modeling.backend.logic.demand import ModelDemand


def record_model_demand(team_id: int, saved_query_ids: Collection[str]) -> None:
    ModelDemand.record(team_id, saved_query_ids)
