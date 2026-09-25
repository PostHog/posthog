import re
import json
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.customer_analytics.backend.facade.enums import AccountViewVisibility
from products.customer_analytics.backend.models.account_view import AccountView
from products.notebooks.backend.facade import content as notebook_content
from products.notebooks.backend.facade.contracts import NotebookMarkdownContentInvalid

ACCOUNT_VIEW_COMPONENT_LABELS = {
    "Notes": "Notes",
    "Tasks": "Tasks",
    "Users": "Users",
    "Relationships": "Relationships",
    "FeatureRequests": "Feature requests",
    "Usage": "Usage",
    "Spend": "Spend",
    "Opportunities": "Opportunities",
    "Conversations": "Conversations",
    "Meetings": "Meetings",
    "EventStream": "Event stream",
}
ACCOUNT_VIEW_ALLOWED_PROPS = {"config", "nodeId", "title"}
ACCOUNT_VIEW_COMPONENT_TITLE_MAX_LENGTH = 400
ACCOUNT_VIEW_CONFIG_MAX_BYTES = 16_384
ACCOUNT_VIEW_IDENTITY_PROPS = {
    "accountId",
    "account_id",
    "externalId",
    "external_id",
    "projectId",
    "project_id",
    "teamId",
    "team_id",
}
ACCOUNT_VIEW_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")


class InvalidAccountViewContent(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class AccountViewVersionConflict(Exception):
    pass


def get_account_identity_props(value: object) -> set[str]:
    if isinstance(value, dict):
        return ACCOUNT_VIEW_IDENTITY_PROPS.intersection(value) | set().union(
            *(get_account_identity_props(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(get_account_identity_props(item) for item in value))
    return set()


def list_account_views(*, team_id: int, user_id: int) -> list[AccountView]:
    return list(
        AccountView.objects.for_team(team_id)
        .filter(created_by_id=user_id, deleted_at__isnull=True, visibility=AccountViewVisibility.PRIVATE)
        .order_by("name", "created_at")
    )


def get_account_view(*, team_id: int, user_id: int, view_id: UUID) -> AccountView | None:
    return (
        AccountView.objects.for_team(team_id)
        .filter(
            id=view_id,
            created_by_id=user_id,
            deleted_at__isnull=True,
            visibility=AccountViewVisibility.PRIVATE,
        )
        .first()
    )


def validate_account_view_content(content: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        components = notebook_content.parse_markdown_component_document(content)
    except NotebookMarkdownContentInvalid as error:
        raise InvalidAccountViewContent([str(error)]) from error

    if not components:
        raise InvalidAccountViewContent(["Add at least one component."])

    errors: list[str] = []
    node_ids: set[str] = set()
    labels: list[str] = []
    for index, component in enumerate(components, start=1):
        label = ACCOUNT_VIEW_COMPONENT_LABELS.get(component.tag_name)
        if label is None:
            errors.append(f"Component {index} uses unknown type {component.tag_name}.")
            continue
        title = component.props.get("title")
        if title is None:
            labels.append(label)
        elif not isinstance(title, str) or not title.strip() or len(title) > ACCOUNT_VIEW_COMPONENT_TITLE_MAX_LENGTH:
            errors.append(f"Component {index} title must be a non-empty string up to 400 characters.")
        else:
            labels.append(title.strip())

        identity_props = ACCOUNT_VIEW_IDENTITY_PROPS.intersection(component.props)
        if identity_props:
            errors.append(f"Component {index} cannot set account identity.")

        unknown_props = set(component.props).difference(ACCOUNT_VIEW_ALLOWED_PROPS)
        if unknown_props:
            errors.append(f"Component {index} has unsupported properties: {', '.join(sorted(unknown_props))}.")

        node_id = component.props.get("nodeId")
        if not isinstance(node_id, str) or not ACCOUNT_VIEW_NODE_ID.fullmatch(node_id):
            errors.append(f"Component {index} needs a valid nodeId.")
        elif node_id in node_ids:
            errors.append(f"Component {index} duplicates nodeId {node_id}.")
        else:
            node_ids.add(node_id)

        config = component.props.get("config")
        if config is not None:
            if not isinstance(config, dict):
                errors.append(f"Component {index} config must be an object.")
            elif identity_props := get_account_identity_props(config):
                errors.append(
                    f"Component {index} config cannot set account identity: {', '.join(sorted(identity_props))}."
                )
            elif len(json.dumps(config, separators=(",", ":")).encode()) > ACCOUNT_VIEW_CONFIG_MAX_BYTES:
                errors.append(f"Component {index} config is too large.")

    if errors:
        raise InvalidAccountViewContent(errors)

    return content, "\n".join(labels)


@transaction.atomic
def create_account_view(*, team_id: int, user_id: int, name: str, content: dict[str, Any]) -> AccountView:
    validated_content, text_content = validate_account_view_content(content)
    return AccountView.objects.for_team(team_id).create(
        team_id=team_id,
        name=name,
        visibility=AccountViewVisibility.PRIVATE,
        content=validated_content,
        text_content=text_content,
        created_by_id=user_id,
        last_modified_by_id=user_id,
    )


@transaction.atomic
def update_account_view(
    *,
    team_id: int,
    user_id: int,
    view_id: UUID,
    expected_version: int,
    name: str | None = None,
    content: dict[str, Any] | None = None,
) -> AccountView | None:
    view = (
        AccountView.objects.for_team(team_id)
        .select_for_update()
        .filter(
            id=view_id,
            created_by_id=user_id,
            deleted_at__isnull=True,
            visibility=AccountViewVisibility.PRIVATE,
        )
        .first()
    )
    if view is None:
        return None
    if view.version != expected_version:
        raise AccountViewVersionConflict("This view changed since you opened it.")

    update_fields = ["last_modified_by", "version", "updated_at"]
    if name is not None:
        view.name = name
        update_fields.append("name")
    if content is not None:
        view.content, view.text_content = validate_account_view_content(content)
        update_fields.extend(["content", "text_content"])

    view.last_modified_by_id = user_id
    view.version += 1
    view.save(update_fields=update_fields)
    return view


@transaction.atomic
def delete_account_view(*, team_id: int, user_id: int, view_id: UUID, expected_version: int) -> bool:
    view = (
        AccountView.objects.for_team(team_id)
        .select_for_update()
        .filter(
            id=view_id,
            created_by_id=user_id,
            deleted_at__isnull=True,
            visibility=AccountViewVisibility.PRIVATE,
        )
        .first()
    )
    if view is None:
        return False
    if view.version != expected_version:
        raise AccountViewVersionConflict("This view changed since you opened it.")

    view.deleted_at = timezone.now()
    view.last_modified_by_id = user_id
    view.version += 1
    view.save(update_fields=["deleted_at", "last_modified_by", "version", "updated_at"])
    return True
