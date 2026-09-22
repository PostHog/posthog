from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.models.activity_logging.utils import activity_storage

if TYPE_CHECKING:
    from posthog.models.integration import Integration
    from posthog.models.user import User
    from posthog.models.user_integration import UserIntegration

logger = structlog.get_logger("posthog.github_diagnostics")


@frozen
class GitHubAudit:
    organization_id: UUID | None = None
    team_id: int | None = None
    integration_id: str | None = None
    installation_id: str | None = None
    owner: str | None = None
    user: User | None = None
    personal_metadata: dict[str, Any] | None = None

    @classmethod
    def project(cls, integration: Integration, user: User | None = None) -> GitHubAudit:
        return cls(
            organization_id=integration.team.organization_id,
            team_id=integration.team_id,
            integration_id=str(integration.pk),
            installation_id=integration.integration_id,
            owner=(integration.config.get("account") or {}).get("name"),
            user=user,
        )

    @classmethod
    def personal(cls, integration: UserIntegration, user: User | None = None) -> GitHubAudit:
        config = integration.config or {}
        identity = config.get("github_user") or {}
        try:
            organization_id = (
                UUID(str(config["originating_organization_id"])) if config.get("originating_organization_id") else None
            )
        except (ValueError, TypeError):
            organization_id = None
        return cls(
            organization_id=organization_id,
            integration_id=str(integration.pk),
            installation_id=integration.integration_id,
            user=user,
            personal_metadata={
                "personal_integration_id": str(integration.pk),
                "owning_user_id": integration.user_id,
                "github_user_id": identity.get("id"),
                "github_login": identity.get("login"),
                "credential_version": config.get("credential_version"),
                "identity_verified_at": config.get("identity_verified_at"),
            },
        )

    def record(
        self, event: str, *, after_commit: bool = False, customer_visible: bool = False, **evidence: Any
    ) -> None:
        was_impersonated = bool(self.user and activity_storage.get_was_impersonated())
        payload = {
            "integration_id": self.integration_id,
            "installation_id": self.installation_id,
            "installation_owner": self.owner,
            **(self.personal_metadata or {}),
            **evidence,
        }

        def write() -> None:
            logger.info(
                event,
                organization_id=str(self.organization_id) if self.organization_id else None,
                team_id=self.team_id,
                actor_id=self.user.pk if self.user else None,
                **payload,
            )
            if self.organization_id is None:
                return
            try:
                from posthog.models.activity_logging.activity_log import (  # noqa: PLC0415 -- avoids the integration model import cycle
                    Detail,
                    Trigger,
                    log_activity,
                )

                with transaction.atomic():
                    log_activity(
                        organization_id=self.organization_id,
                        team_id=self.team_id,
                        user=self.user,
                        item_id=self.integration_id or self.installation_id,
                        scope="Integration",
                        activity=event if customer_visible else "github_diagnostic",
                        detail=Detail(
                            name=self.owner or self.installation_id or "GitHub",
                            trigger=Trigger(
                                job_type="github",
                                job_id=str(evidence.get("discovery_id") or ""),
                                payload={"event": event, **payload},
                            ),
                        ),
                        was_impersonated=was_impersonated,
                    )
            except Exception:
                logger.warning("github_audit_write_failed", event_name=event, team_id=self.team_id)

        if after_commit:
            transaction.on_commit(write, robust=True)
        else:
            write()
