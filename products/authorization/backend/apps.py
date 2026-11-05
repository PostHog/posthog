"""Django app configuration for authorization."""

from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save

from .logic import session

# A write to these models clears the session's cached rules.
RULE_MODELS = ("ee.AccessControl", "ee.RoleMembership", "posthog.OrganizationMembership")


class AuthorizationConfig(AppConfig):
    name = "products.authorization.backend"
    label = "authorization"

    def ready(self) -> None:
        for model in RULE_MODELS:
            post_save.connect(session.invalidate, sender=model, dispatch_uid=f"authorization-save-{model}")
            post_delete.connect(session.invalidate, sender=model, dispatch_uid=f"authorization-delete-{model}")
