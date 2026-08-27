"""
Model-class wiring for autoresearch.

Light re-exports of the model classes cross-product object-consumers need
(HogQL system-table test fixtures). Prefer the facade's contract-returning
functions for data access; import from here only when the consumer genuinely
needs the model class itself.
"""

from products.autoresearch.backend.models import AutoresearchPipeline

__all__ = ["AutoresearchPipeline"]
