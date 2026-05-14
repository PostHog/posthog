"""
Django models for agent_stack.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

import uuid

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel

from .facade.enums import SplineStatus


class SplineReticulator(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in SplineStatus],
        default=SplineStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name
