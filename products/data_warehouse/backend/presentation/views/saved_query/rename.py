from collections.abc import Sequence
from typing import TYPE_CHECKING

from rest_framework import exceptions, serializers

from posthog.hogql.database.database import Database

from posthog.exceptions import Conflict

from products.data_modeling.backend.facade.modeling import ModelRenamePlan, plan_model_rename
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class RenamePlanRequestSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=128, help_text="New model name. The models namespace is added when omitted."
    )


class RenameDependentSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the dependent model.")
    name = serializers.CharField(help_text="Current name of the dependent model.")
    before = serializers.CharField(help_text="Stored SQL before the rename.")
    after = serializers.CharField(help_text="SQL with model references rewritten.")


class RenameBlockedSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the model blocking the rename.")
    name = serializers.CharField(help_text="Current name of the model blocking the rename.")
    reason = serializers.CharField(help_text="Why the SQL cannot be rewritten safely.")


class RenamePlanSerializer(serializers.Serializer):
    dependents = RenameDependentSerializer(many=True, help_text="Models whose SQL will change.")
    blocked = RenameBlockedSerializer(many=True, help_text="Models that must be fixed before the rename can proceed.")
    plan_token = serializers.CharField(
        help_text="Send this as rename_plan_token with the name in the saved-query update."
    )


def build_rename_plan(
    source: DataWarehouseSavedQuery,
    name: str,
    candidates: Sequence[DataWarehouseSavedQuery],
    access_control: "UserAccessControl | None",
) -> ModelRenamePlan:
    database = Database.create_for(team_id=source.team_id)
    plan = plan_model_rename(source, name, candidates, database)
    affected = {item.id for item in [*plan.dependents, *plan.blocked]}
    if access_control is not None:
        for candidate in candidates:
            if candidate.pk in affected and not access_control.check_access_level_for_object(candidate, "editor"):
                raise exceptions.PermissionDenied(
                    "You need edit access to every dependent model before renaming this model."
                )
    return plan


def validate_rename_plan(plan: ModelRenamePlan, token: str | None) -> None:
    if token != plan.plan_token:
        raise Conflict("The rename plan changed. Preview the rename again before applying it.")
    if plan.blocked:
        raise serializers.ValidationError(
            "Some dependent queries cannot be rewritten. Fix the blocked queries and preview the rename again."
        )
