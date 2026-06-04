"""Render display IDs as the serialized primary key.

Any model that sets ``display_id_prefix`` (via ``DisplayIDModel``) automatically gets its
primary key serialized as a Stripe-style display ID (e.g. ``task_2aUyqjCzEIiEcYMKj7TZtw``)
instead of the raw UUID — no per-serializer field needed. Lookups already accept display IDs
via ``TeamAndOrgViewSetMixin.get_object``, so the prefixed id round-trips.

This wraps ``ModelSerializer.build_standard_field`` so the *auto-built* primary key field
becomes a read-only ``DisplayIDField`` for prefixed models. Models without a prefix and
serializers that declare their ``id`` field explicitly are left untouched.
"""

from __future__ import annotations

from typing import Any

from django_display_ids.contrib.rest_framework import DisplayIDField
from rest_framework.serializers import ModelSerializer

_PATCHED_FLAG = "_display_id_pk_patched"


def patch_model_serializer_display_id_pk() -> None:
    """Idempotently wrap ``ModelSerializer.build_standard_field`` to emit display-ID pks."""
    if getattr(ModelSerializer, _PATCHED_FLAG, False):
        return

    original_build_standard_field = ModelSerializer.build_standard_field

    def build_standard_field(self: ModelSerializer, field_name: str, model_field: Any) -> Any:
        field_class, field_kwargs = original_build_standard_field(self, field_name, model_field)
        if model_field.primary_key and getattr(model_field.model, "display_id_prefix", None) is not None:
            return DisplayIDField, {"read_only": True}
        return field_class, field_kwargs

    ModelSerializer.build_standard_field = build_standard_field  # type: ignore[method-assign]
    setattr(ModelSerializer, _PATCHED_FLAG, True)
