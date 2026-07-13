"""Model-class re-exports.

The one place external code (information_schema loaders, admin, fixtures) and this product's
own presentation layer are allowed to reach the ORM classes, keeping direct model imports off
the isolation boundary.
"""

from ..models import Metric

__all__ = ["Metric"]
