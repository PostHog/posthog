from typing import Any

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model
from django.db.models.signals import ModelSignal, post_delete, post_save
from django.dispatch import receiver

from products.access_control.backend.facade.api import delete_object_access_controls_for_object
from products.access_control.backend.facade.user_access_control import model_to_resource


def _drop_rules_when_object_is_gone(
    sender: type[Model], instance: Model, signal: ModelSignal, raw: bool = False, **_kwargs: Any
) -> None:
    # A rule points at its object by id and has no foreign key to it. Django does not delete the
    # rule when the object is deleted. Skip a save that does not set the deleted flag, so that a
    # normal save runs no query.
    if raw or (signal is post_save and getattr(instance, "deleted", None) is not True):
        return
    resource = model_to_resource(sender)
    team_id = getattr(instance, "team_id", None)
    if resource is None or team_id is None:
        return
    delete_object_access_controls_for_object(team_id=team_id, resource=resource, resource_id=str(instance.pk))


def _has_field(model: type[Model], field: str) -> bool:
    try:
        model._meta.get_field(field)
        return True
    except FieldDoesNotExist:
        return False


def _can_carry_object_rules(model: type[Model]) -> bool:
    resource = model_to_resource(model)
    # Project access is a resource-level rule on the team row. It is not an object rule. A model
    # with no team of its own cannot carry one either, because every rule is scoped to a team.
    if resource is None or resource == "project":
        return False
    return _has_field(model, "team") or _has_field(model, "team_id")


def connect_object_rule_cleanup() -> None:
    """Connect the cleanup receivers to one sender each, never to every model at once.

    A receiver registered without a sender answers post_delete.has_listeners() for every model, and
    Django then refuses the fast-delete path for all of them: a bulk delete or a cascade loads every
    row into memory and dispatches per row instead of issuing one DELETE. Naming the sender leaves
    that path alone for the models that carry no object rules.

    These are plain receivers, not mutable_receiver ones. The project tree deletes an object
    inside mute_selected_signals(), and those are everyday single-item and folder deletes that must
    still drop the rules. The product's other receivers are plain for the same reason.

    Call this from the app's ready(), where the model registry is populated.
    """
    for model in apps.get_models():
        if not _can_carry_object_rules(model):
            continue
        receiver(post_delete, sender=model)(_drop_rules_when_object_is_gone)
        # Only a model that carries the flag can leave a save soft-deleted
        if _has_field(model, "deleted"):
            receiver(post_save, sender=model)(_drop_rules_when_object_is_gone)
