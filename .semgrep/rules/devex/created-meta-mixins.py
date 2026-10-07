# Test cases for created-by-uses-created-meta-mixin and created-at-uses-created-meta-mixin.
# ruff: noqa
from django.db import models
from django.db.models import ForeignKey
from django.utils import timezone

from posthog.models.utils import CreatedMetaFields, IsolatedProductCreatedMetaFields, UUIDModel


class HandWritten(UUIDModel):
    # ruleid: created-by-uses-created-meta-mixin
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)


class HandWrittenWithoutConstraint(UUIDModel):
    # ruleid: created-by-uses-created-meta-mixin
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )


class OverridesTheMixin(CreatedMetaFields, UUIDModel):
    # ruleid: created-by-uses-created-meta-mixin
    created_by = ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)


class Annotated(UUIDModel):
    # ruleid: created-by-uses-created-meta-mixin
    created_by: models.ForeignKey = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)


# ok: created-by-uses-created-meta-mixin
class UsesTheMixin(CreatedMetaFields, UUIDModel):
    name = models.CharField(max_length=400)


# ok: created-by-uses-created-meta-mixin
class UsesTheIsolatedMixin(IsolatedProductCreatedMetaFields, UUIDModel):
    name = models.CharField(max_length=400)


class DifferentDeleteBehavior(UUIDModel):
    # ok: created-by-uses-created-meta-mixin
    created_by = models.ForeignKey(  # nosemgrep: created-by-uses-created-meta-mixin
        "posthog.User", on_delete=models.CASCADE
    )


class OtherUserField(UUIDModel):
    # ok: created-by-uses-created-meta-mixin
    last_modified_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)


class OverridesCreatedAt(CreatedMetaFields, UUIDModel):
    # ruleid: created-at-uses-created-meta-mixin
    created_at = models.DateTimeField(default=timezone.now)


class OverridesCreatedAtOnIsolated(TeamScopedRootMixin, IsolatedProductCreatedMetaFields, UUIDModel):
    # ruleid: created-at-uses-created-meta-mixin
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)


class NullableCreatedAt(CreatedMetaFields, UUIDModel):
    # ok: created-at-uses-created-meta-mixin
    created_at = models.DateTimeField(  # nosemgrep: created-at-uses-created-meta-mixin
        auto_now_add=True, null=True
    )


class OwnCreatedAtWithoutMixin(UUIDModel):
    # ok: created-at-uses-created-meta-mixin
    created_at = models.DateTimeField(auto_now_add=True)
