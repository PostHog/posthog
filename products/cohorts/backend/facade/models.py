"""
Model-class wiring for cohorts.

Re-exports the ``Cohort`` model class under the watched-models allowance (MODEL_CROSSINGS).
The insight API's legacy query path raises ``Cohort.DoesNotExist`` from inside filter
resolution and turns it into a 400 — catching a model's own exception needs the class, and
the tests that cover that path build cohort rows through the manager.
"""

from products.cohorts.backend.models.cohort import Cohort

__all__ = ["Cohort"]
