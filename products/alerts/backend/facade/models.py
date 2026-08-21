"""
Model-class wiring for alerts.

Re-exports the ``AlertConfiguration``, ``AlertSubscription`` and ``Threshold`` model classes
under the watched-models allowance (MODEL_CROSSINGS). The insight API prefetches an insight's
alerts with a ``Prefetch`` queryset so rendering them costs no extra query, and soft-deletes
them alongside the insight — ORM semantics a frozen contract cannot express. ``Threshold`` and
``AlertSubscription`` hang off ``AlertConfiguration`` and cross with it, because the rendered
alert carries its threshold and its subscribers.
"""

from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription, Threshold

__all__ = ["AlertConfiguration", "AlertSubscription", "Threshold"]
