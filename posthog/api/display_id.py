"""Serialize Stripe-style display IDs for models that opt in via ``display_id_prefix``.

A model that sets ``display_id_prefix`` (see ``DisplayIDModel``) gets a display ID
(e.g. ``task_2aUyqjCzEIiEcYMKj7TZtw``, a base62 encoding of its UUID) in its API
representation automatically — no per-serializer field needed. How it's exposed is
controlled by ``display_id_as_pk`` on the model (default ``True``):

- ``display_id_as_pk = True`` (default): the serialized ``id`` *is* the display ID. Best
  for new models — the prefixed ID is the public identifier everywhere.
- ``display_id_as_pk = False``: ``id`` stays the raw UUID and the display ID is exposed as
  a separate read-only ``display_id`` field. Best for existing models whose ``id`` clients
  already rely on as a UUID.

Either way lookups accept both the display ID and the UUID (see
``TeamAndOrgViewSetMixin.get_object``), so the IDs round-trip.

Implemented by wrapping ``ModelSerializer.get_fields`` so it applies to every model
serializer automatically. A serializer that declares its ``id`` field explicitly opts out
of the pk swap — its declared field is left untouched.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from django_display_ids.contrib.rest_framework import DisplayIDField
from rest_framework.serializers import ModelSerializer

_PATCHED_FLAG = "_display_id_fields_patched"


def serializes_display_id_as_pk(model: type[models.Model]) -> bool:
    """Whether a prefixed ``model`` serializes its display ID as the ``id`` field.

    Defaults to ``True`` so adopting display IDs needs only ``display_id_prefix``; a model
    sets ``display_id_as_pk = False`` to keep a raw-UUID ``id`` and expose ``display_id``
    as a separate field instead.
    """
    return bool(getattr(model, "display_id_as_pk", True))


def patch_model_serializer_display_id() -> None:
    """Idempotently wrap ``ModelSerializer.get_fields`` to serialize display IDs."""
    if getattr(ModelSerializer, _PATCHED_FLAG, False):
        return

    original_get_fields = ModelSerializer.get_fields

    def get_fields(self: ModelSerializer) -> Any:
        fields = original_get_fields(self)

        model = getattr(getattr(self, "Meta", None), "model", None)
        if model is None or getattr(model, "display_id_prefix", None) is None:
            return fields

        if serializes_display_id_as_pk(model):
            # Swap the auto-built primary key field for a display-ID field. An explicitly
            # declared id field is the opt-out, so leave it alone.
            pk_name = model._meta.pk.name
            if pk_name in fields and pk_name not in self._declared_fields:
                fields[pk_name] = DisplayIDField()
        elif "display_id" not in fields:
            fields["display_id"] = DisplayIDField()

        return fields

    ModelSerializer.get_fields = get_fields  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    setattr(ModelSerializer, _PATCHED_FLAG, True)
