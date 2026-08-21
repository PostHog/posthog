"""
Model-class wiring for dashboards.

Re-exports the ``Dashboard``, ``DashboardTile`` and ``Text`` model classes for cross-product
consumers under the watched-models allowance (MODEL_CROSSINGS). The insight API renders an
insight's dashboard membership: it resolves target dashboards through querysets, reads
privilege levels off the model, serializes tiles with a ``ModelSerializer``, and creates,
soft-deletes and restores tiles — ORM semantics a frozen contract cannot express. ``Text``
crosses with ``DashboardTile`` because a tile carries either an insight or a text block.
"""

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text

__all__ = ["Dashboard", "DashboardTile", "Text"]
