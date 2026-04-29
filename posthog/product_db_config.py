from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PRODUCT_DB_ROUTING_FILE = "products/db_routing.yaml"


@dataclass(frozen=True)
class ProductDBRoute:
    app_label: str
    database: str
    source: str

    def routes_model(self, model: object) -> bool:
        model_meta = getattr(model, "_meta", None)
        if model_meta is None:
            return False

        return model_meta.app_label == self.app_label


def load_product_db_routes(base_dir: Path | str) -> tuple[ProductDBRoute, ...]:
    config_path = Path(base_dir) / PRODUCT_DB_ROUTING_FILE
    if not config_path.exists():
        return ()

    with config_path.open() as f:
        config = yaml.safe_load(f) or {}

    routes: list[ProductDBRoute] = []
    for route_config in config.get("routes", []):
        app_label = str(route_config.get("app_label", "")).strip()
        database = str(route_config.get("database", "")).strip()

        if not app_label or not database:
            logger.warning(
                "Incomplete product DB route entry in %s: app_label=%r, database=%r", config_path, app_label, database
            )
            continue

        routes.append(
            ProductDBRoute(
                app_label=app_label,
                database=database,
                source=str(config_path),
            )
        )

    return tuple(routes)
