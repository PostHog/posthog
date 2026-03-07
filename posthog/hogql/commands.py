from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.errors import QueryError

from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.personal_api_key_service import (
    create_personal_api_key,
    list_personal_api_keys,
    roll_personal_api_key,
    validate_scopes,
)


def execute_command(
    node: ast.Expr,
    user: User,
) -> HogQLQueryResponse:
    if isinstance(node, ast.CreateApiKeyCommand):
        try:
            validate_scopes(node.scopes)
        except ValueError as e:
            raise QueryError(str(e))
        try:
            key, raw_value = create_personal_api_key(user, node.label, node.scopes)
        except ValueError as e:
            raise QueryError(str(e))
        return HogQLQueryResponse(
            results=[[raw_value, key.label, key.scopes, str(key.created_at)]],
            columns=["api_key", "label", "scopes", "created_at"],
            types=["String", "String", "Array(String)", "DateTime"],
        )

    if isinstance(node, ast.ShowApiKeysCommand):
        keys = list_personal_api_keys(user)
        rows = [
            [
                str(k.id),
                k.label,
                k.mask_value,
                k.scopes or ["*"],
                str(k.created_at),
                str(k.last_used_at) if k.last_used_at else None,
                str(k.last_rolled_at) if k.last_rolled_at else None,
            ]
            for k in keys
        ]
        return HogQLQueryResponse(
            results=rows,
            columns=["id", "label", "mask_value", "scopes", "created_at", "last_used_at", "last_rolled_at"],
            types=["String", "String", "String", "Array(String)", "DateTime", "DateTime", "DateTime"],
        )

    if isinstance(node, ast.AlterApiKeyRollCommand):
        key = PersonalAPIKey.objects.filter(user=user, label=node.label).first()
        if not key:
            raise QueryError(f"API key '{node.label}' not found")
        key, raw_value = roll_personal_api_key(key)
        return HogQLQueryResponse(
            results=[[raw_value, key.label, str(key.last_rolled_at)]],
            columns=["api_key", "label", "last_rolled_at"],
            types=["String", "String", "DateTime"],
        )

    raise QueryError(f"Unknown command type: {type(node).__name__}")
