from typing import Any

from django.db.models import Model
from django.db.models.signals import post_delete, post_save

from posthog.models.signals import mutable_receiver

from products.access_control.backend.facade.api import delete_object_access_controls_for_object
from products.access_control.backend.facade.user_access_control import model_to_resource


def _drop_rules(sender: type[Model], instance: Model) -> None:
    resource = model_to_resource(sender)
    team_id = getattr(instance, "team_id", None)
    # Project access is a resource-level control on the team row, never an object rule
    if resource is None or resource == "project" or team_id is None:
        return
    delete_object_access_controls_for_object(team_id=team_id, resource=resource, resource_id=str(instance.pk))


@mutable_receiver(post_save)
def _drop_rules_on_soft_delete(sender: type[Model], instance: Model, raw: bool = False, **_kwargs: Any) -> None:
    # Rules have no foreign key to their object, so nothing cascades when the object goes away.
    # Only a save that leaves the object soft-deleted pays for the lookup
    if raw or getattr(instance, "deleted", None) is not True:
        return
    _drop_rules(sender, instance)


@mutable_receiver(post_delete)
def _drop_rules_on_delete(sender: type[Model], instance: Model, **_kwargs: Any) -> None:
    _drop_rules(sender, instance)
