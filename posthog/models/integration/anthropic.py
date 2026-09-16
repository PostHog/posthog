"""Anthropic Managed Agents integration."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anthropic import Anthropic

from django.db import transaction

import structlog
from rest_framework.exceptions import ValidationError

from posthog.models.user import User
from posthog.models.utils import IntegrityError

from . import model

logger = structlog.get_logger(__name__)


ANTHROPIC_MANAGED_AGENTS_BETA_HEADER = "managed-agents-2026-04-01"

ANTHROPIC_DEFAULT_INTEGRATION_ID_PREFIX = "workspace-"

ANTHROPIC_WORKSPACE_LABEL_MAX_LENGTH = 100

ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT = 100

# 5s connect / 15s read are aggressive enough to keep gunicorn workers from
# being pinned for ~minutes on a slow Anthropic upstream while still leaving
# headroom for normal API latency.
ANTHROPIC_CLIENT_TIMEOUT_SECONDS = 15.0


class AnthropicIntegrationError(Exception):
    """Raised when the AnthropicIntegration is constructed with an invalid Integration row."""


def _build_anthropic_client(api_key: str) -> "Anthropic":
    # Tight timeouts and no SDK-side retries: we don't want a slow upstream to
    # multiply request time by 3 (default `max_retries=2`) inside a Django worker.
    from anthropic import Anthropic  # noqa: PLC0415

    return Anthropic(api_key=api_key, timeout=ANTHROPIC_CLIENT_TIMEOUT_SECONDS, max_retries=0)


class AnthropicIntegration:
    integration: model.Integration
    _client: "Anthropic"

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != model.Integration.IntegrationKind.ANTHROPIC.value:
            # Internal misuse, not a user-input issue.
            raise AnthropicIntegrationError(
                f"AnthropicIntegration init called with Integration kind={integration.kind!r}"
            )
        self.integration = integration
        api_key = integration.sensitive_config.get("api_key")
        if not api_key:
            raise AnthropicIntegrationError(f"Anthropic integration {integration.id} is missing 'api_key'")
        self._client = _build_anthropic_client(api_key)

    @staticmethod
    def validate_key(api_key: str) -> None:
        # Validate by hitting the actual managed-agents surface so a key without
        # beta access fails at create time instead of silently failing later.
        from anthropic import (  # noqa: PLC0415
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            PermissionDeniedError,
        )

        try:
            client = _build_anthropic_client(api_key)
            client.get(
                "/v1/agents",
                cast_to=dict[str, object],
                options={
                    "headers": {"anthropic-beta": ANTHROPIC_MANAGED_AGENTS_BETA_HEADER},
                    "params": {"limit": 1},
                },
            )
        except AuthenticationError:
            raise ValidationError({"api_key": "Invalid Anthropic API key"})
        except PermissionDeniedError:
            raise ValidationError(
                {
                    "api_key": (
                        "Anthropic API key is missing required permissions. Make sure the key has access to the "
                        "Managed Agents beta in your Anthropic console."
                    )
                }
            )
        except APIConnectionError:
            logger.warning("anthropic_validate_key_connection_error", exc_info=True)
            raise ValidationError(
                {"api_key": "Could not reach Anthropic to validate the API key. Check your network and try again."}
            )
        except APIStatusError as e:
            logger.warning("anthropic_validate_key_status_error", status_code=e.status_code, exc_info=True)
            raise ValidationError(
                {"api_key": f"Anthropic returned an error validating the API key (HTTP {e.status_code})."}
            )

    def _managed_agents_get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return self._client.get(
            path,
            cast_to=dict[str, object],
            options={
                "headers": {"anthropic-beta": ANTHROPIC_MANAGED_AGENTS_BETA_HEADER},
                "params": params or {},
            },
        )

    def _list_managed_agents_resource(self, path: str, after: str | None, limit: int) -> tuple[list[dict], str | None]:
        params: dict[str, Any] = {"limit": min(max(int(limit), 1), ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT)}
        if after:
            params["after"] = after
        response = self._managed_agents_get(path, params=params)
        raw_data = response.get("data", [])
        data: list[dict] = [item for item in raw_data if isinstance(item, dict)] if isinstance(raw_data, list) else []
        next_cursor = response.get("next_cursor")
        return data, next_cursor if isinstance(next_cursor, str) else None

    def list_managed_agents(
        self, after: str | None = None, limit: int = ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT
    ) -> tuple[list[dict], str | None]:
        return self._list_managed_agents_resource("/v1/agents", after=after, limit=limit)

    def list_managed_agent_environments(
        self, after: str | None = None, limit: int = ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT
    ) -> tuple[list[dict], str | None]:
        return self._list_managed_agents_resource("/v1/environments", after=after, limit=limit)

    def list_managed_agent_vaults(
        self, after: str | None = None, limit: int = ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT
    ) -> tuple[list[dict], str | None]:
        return self._list_managed_agents_resource("/v1/vaults", after=after, limit=limit)

    @classmethod
    def integration_from_key(
        cls,
        api_key: str,
        team_id: int,
        created_by: User,
        workspace_label: str | None = None,
        force: bool = False,
    ) -> model.Integration:
        cls.validate_key(api_key)

        anthropic_kind: str = model.Integration.IntegrationKind.ANTHROPIC.value
        integration_id = workspace_label or f"{ANTHROPIC_DEFAULT_INTEGRATION_ID_PREFIX}{team_id}"
        config: dict[str, Any] = {}
        if workspace_label:
            config["workspace_label"] = workspace_label

        if force:
            integration, _ = model.Integration.objects.update_or_create(
                team_id=team_id,
                kind=anthropic_kind,
                integration_id=integration_id,
                defaults={
                    "config": config,
                    "sensitive_config": {"api_key": api_key},
                    "created_by": created_by,
                    "errors": "",
                },
            )
            return integration

        try:
            # Wrap in a savepoint so the unique-constraint IntegrityError below
            # aborts only the INSERT, not the surrounding transaction (e.g. the
            # outer DRF request atomic block, or the test wrapper).
            with transaction.atomic():
                return model.Integration.objects.create(
                    team_id=team_id,
                    kind=anthropic_kind,
                    integration_id=integration_id,
                    config=config,
                    sensitive_config={"api_key": api_key},
                    created_by=created_by,
                    errors="",
                )
        except IntegrityError:
            raise ValidationError(
                {
                    "config": (
                        f"An integration with id '{integration_id}' already exists for this team. Choose a different "
                        "workspace label, delete the existing integration and try again, or set 'force' to true to overwrite the existing integration."
                    )
                }
            )
