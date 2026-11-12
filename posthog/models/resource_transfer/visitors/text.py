from django.db import models

from posthog.models.resource_transfer.registered_models import registered_model
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class TextVisitor(ResourceTransferVisitor, kind="Text", excluded_fields=["last_modified_at"], user_facing=False):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        # The dashboards product registers its model from its AppConfig.ready().
        return registered_model("Text")
