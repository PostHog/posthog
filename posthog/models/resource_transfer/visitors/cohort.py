from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class CohortVisitor(
    ResourceTransferVisitor,
    kind="Cohort",
    excluded_fields=[
        "is_calculating",
        "last_calculation",
        "errors_calculating",
        "last_error_at",
        "count",
        "version",
        "pending_version",
        "people",
        "groups",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Cohort

        return Cohort
