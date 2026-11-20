"""Django app configuration for authorization."""

from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save

from products.access_control.backend.facade.change_signals import connect_role_access_invalidated

from .logic import session

# A write to these models clears the session's cached rules.
RULE_MODELS = ("ee.AccessControl", "ee.RoleMembership", "posthog.OrganizationMembership")


class AuthorizationConfig(AppConfig):
    name = "products.authorization.backend"
    label = "authorization"

    def ready(self) -> None:
        connect_role_access_invalidated(session.invalidate, dispatch_uid="authorization-role-access-invalidated")
        for model in RULE_MODELS:
            post_save.connect(session.invalidate, sender=model, dispatch_uid=f"authorization-save-{model}")
            post_delete.connect(session.invalidate, sender=model, dispatch_uid=f"authorization-delete-{model}")
