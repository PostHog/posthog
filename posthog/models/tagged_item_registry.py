"""Which models may carry tags, and how each one is addressed on a TaggedItem row.

TaggedItem points at its object with two typed columns, `object_id` for integer-keyed
models and `object_uuid` for UUID-keyed ones, rather than the single text column a
textbook generic relation uses. Postgres has to cast a join column when the two sides
differ in type, and Django puts that cast on the TaggedItem side, which makes the index
on the object column unusable for every `tagged_items__...` lookup. Two typed columns
keep both joins cast-free.

`object_id` is a plain integer even though `Project.id` is a bigint. Project ids are
drawn from `posthog_team_id_seq`, an integer sequence, so they always fit. Only Project
pays for the mismatch, with a widening cast that cannot fail. Sizing the column to bigint
instead would move the cast onto every other integer-keyed model, and make it a narrowing
cast that can overflow.

This module holds no Django model imports, so it is safe to import from anywhere,
including `posthog/models/tagged_item.py` itself.
"""

from __future__ import annotations

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import models

from posthog.dataclasses import frozen

OBJECT_ID = "object_id"
OBJECT_UUID = "object_uuid"


@frozen
class TaggableModel:
    """One taggable model, and the three things tag code needs to know about it."""

    model_label: str
    """Django `app_label.ModelName`, resolved lazily so this module imports no models."""

    legacy_field: str
    """The pre-generic-relation foreign key name on TaggedItem.

    This string is also persisted in activity-log rows as `related_object_type`, and the
    frontend describer switches on it, so it must keep its exact spelling even after the
    foreign key column is gone.
    """

    object_field: str
    """Which typed column on TaggedItem holds this model's primary key."""


TAGGABLE_MODELS: tuple[TaggableModel, ...] = (
    TaggableModel(model_label="dashboards.Dashboard", legacy_field="dashboard", object_field=OBJECT_ID),
    TaggableModel(model_label="product_analytics.Insight", legacy_field="insight", object_field=OBJECT_ID),
    TaggableModel(
        model_label="event_definitions.EventDefinition", legacy_field="event_definition", object_field=OBJECT_UUID
    ),
    TaggableModel(
        model_label="event_definitions.PropertyDefinition", legacy_field="property_definition", object_field=OBJECT_UUID
    ),
    TaggableModel(model_label="actions.Action", legacy_field="action", object_field=OBJECT_ID),
    TaggableModel(model_label="feature_flags.FeatureFlag", legacy_field="feature_flag", object_field=OBJECT_ID),
    TaggableModel(
        model_label="experiments.ExperimentSavedMetric",
        legacy_field="experiment_saved_metric",
        object_field=OBJECT_ID,
    ),
    TaggableModel(model_label="conversations.Ticket", legacy_field="ticket", object_field=OBJECT_UUID),
    TaggableModel(model_label="customer_analytics.Account", legacy_field="account", object_field=OBJECT_UUID),
    TaggableModel(model_label="endpoints.Endpoint", legacy_field="endpoint", object_field=OBJECT_UUID),
    TaggableModel(model_label="replay_vision.ReplayScanner", legacy_field="replay_scanner", object_field=OBJECT_UUID),
    TaggableModel(model_label="posthog.Project", legacy_field="project", object_field=OBJECT_ID),
    TaggableModel(model_label="experiments.Experiment", legacy_field="experiment", object_field=OBJECT_ID),
)

_BY_LABEL: dict[str, TaggableModel] = {entry.model_label: entry for entry in TAGGABLE_MODELS}
_BY_LEGACY_FIELD: dict[str, TaggableModel] = {entry.legacy_field: entry for entry in TAGGABLE_MODELS}


class NotTaggableError(ValueError):
    """Raised when tag code is handed a model that the registry does not list."""


def taggable_for(model: type[models.Model]) -> TaggableModel | None:
    """The registry entry for a model, or None when the model is not taggable.

    A multi-table-inheritance child resolves to its registered base. `EnterpriseEventDefinition`
    therefore answers with the `EventDefinition` entry. Django resolves a generic relation's
    content type from the instance's own class, so without this every enterprise definition
    would tag itself under a second content type and its tags would stop matching the ones
    written through the base model's API.
    """
    for klass in model.__mro__:
        meta = getattr(klass, "_meta", None)
        entry = _BY_LABEL.get(getattr(meta, "label", ""))
        if entry is not None:
            return entry
    return None


def require_taggable(model: type[models.Model]) -> TaggableModel:
    """The registry entry for a model, raising when it is not taggable."""
    entry = taggable_for(model)
    if entry is None:
        raise NotTaggableError(f"{model._meta.label} is not a taggable model. Add it to TAGGABLE_MODELS.")
    return entry


def taggable_for_legacy_field(legacy_field: str) -> TaggableModel | None:
    """The registry entry for a pre-generic-relation foreign key name."""
    return _BY_LEGACY_FIELD.get(legacy_field)


def base_model_for(model: type[models.Model]) -> type[models.Model]:
    """The registered base model a taggable model resolves to."""
    return apps.get_model(require_taggable(model).model_label)


def content_type_for(model: type[models.Model]) -> ContentType:
    """The content type a tag on this model is stored under, always the registered base."""
    return content_type_for_entry(require_taggable(model))


def content_type_for_entry(entry: TaggableModel) -> ContentType:
    """The content type for a registry entry, without needing the model class in hand."""
    return ContentType.objects.get_for_model(apps.get_model(entry.model_label))


def object_column_for(model: type[models.Model]) -> str:
    """Which typed column on TaggedItem holds this model's primary key."""
    return require_taggable(model).object_field


def legacy_field_for(model: type[models.Model]) -> str:
    """The activity-log `related_object_type` string for this model."""
    return require_taggable(model).legacy_field
