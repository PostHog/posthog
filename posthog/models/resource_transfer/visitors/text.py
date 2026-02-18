from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class TextVisitor(ResourceTransferVisitor, kind="Text", excluded_fields=["last_modified_at"], user_facing=False):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Text

        return Text
