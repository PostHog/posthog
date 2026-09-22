from typing import Any

from django.db.models import Model
from django.db.models.signals import ModelSignal, post_delete, post_save

from posthog.models.signals import mutable_receiver

from products.access_control.backend.facade.api import delete_object_access_controls_for_object
from products.access_control.backend.facade.user_access_control import model_to_resource


@mutable_receiver(post_save)
@mutable_receiver(post_delete)
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
    # Project access is a resource-level rule on the team row. It is not an object rule.
    if resource is None or resource == "project" or team_id is None:
        return
    delete_object_access_controls_for_object(team_id=team_id, resource=resource, resource_id=str(instance.pk))
