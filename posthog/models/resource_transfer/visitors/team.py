from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class TeamVisitor(ResourceTransferVisitor, kind="Team", immutable=True, user_facing=False):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Team

        return Team
