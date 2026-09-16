import pytest

from django.apps import apps
from django.db import models

from posthog.models.tagged_item import RELATED_OBJECTS, TaggedItem
from posthog.models.tagged_item_registry import (
    OBJECT_ID,
    OBJECT_UUID,
    TAGGABLE_MODELS,
    TaggableModel,
    base_model_for,
    taggable_for,
)

INTEGER_FIELDS = (models.AutoField, models.IntegerField, models.BigAutoField, models.BigIntegerField)


def _model_for(entry: TaggableModel) -> type[models.Model]:
    return apps.get_model(entry.model_label)


def test_registry_matches_the_foreign_key_fields() -> None:
    assert {entry.legacy_field for entry in TAGGABLE_MODELS} == set(RELATED_OBJECTS)


def test_registry_entries_are_unique() -> None:
    labels = [entry.model_label for entry in TAGGABLE_MODELS]
    legacy_fields = [entry.legacy_field for entry in TAGGABLE_MODELS]
    assert len(set(labels)) == len(labels)
    assert len(set(legacy_fields)) == len(legacy_fields)


@pytest.mark.parametrize("entry", TAGGABLE_MODELS, ids=lambda entry: entry.legacy_field)
def test_object_column_matches_the_primary_key_type(entry: TaggableModel) -> None:
    """A mismatch here would make Postgres cast the object column and stop using its index."""
    primary_key = _model_for(entry)._meta.pk
    assert primary_key is not None

    if entry.object_field == OBJECT_UUID:
        assert isinstance(primary_key, models.UUIDField), (
            f"{entry.model_label} has a {type(primary_key).__name__} primary key, so it belongs on {OBJECT_ID}"
        )
    else:
        assert isinstance(primary_key, INTEGER_FIELDS), (
            f"{entry.model_label} has a {type(primary_key).__name__} primary key, so it belongs on {OBJECT_UUID}"
        )


@pytest.mark.parametrize("entry", TAGGABLE_MODELS, ids=lambda entry: entry.legacy_field)
def test_registry_points_at_the_same_model_as_the_foreign_key(entry: TaggableModel) -> None:
    assert TaggedItem._meta.get_field(entry.legacy_field).related_model is _model_for(entry)


@pytest.mark.parametrize("entry", TAGGABLE_MODELS, ids=lambda entry: entry.legacy_field)
def test_object_column_holds_the_primary_key_range(entry: TaggableModel) -> None:
    """`object_id` is a plain integer, so a bigint-keyed model must still fit inside it."""
    if entry.object_field != OBJECT_ID:
        return
    assert isinstance(TaggedItem._meta.get_field(OBJECT_ID), models.IntegerField)


def test_inherited_models_resolve_to_their_registered_base() -> None:
    """Django reads a generic relation's content type off the instance's own class.

    Without this resolution an enterprise definition would store its tags under a second
    content type, and they would stop matching the tags written through the base model.
    """
    if not apps.is_installed("ee"):
        pytest.skip("needs the ee app")
    enterprise_event_definition = apps.get_model("ee.EnterpriseEventDefinition")
    enterprise_property_definition = apps.get_model("ee.EnterprisePropertyDefinition")

    assert base_model_for(enterprise_event_definition) is apps.get_model("event_definitions.EventDefinition")
    assert base_model_for(enterprise_property_definition) is apps.get_model("event_definitions.PropertyDefinition")


def test_unregistered_models_are_not_taggable() -> None:
    assert taggable_for(apps.get_model("posthog.Team")) is None
