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


class GitHubAuditPayload:
    PERSONAL_FIELDS = frozenset(
        {
            "personal_integration_id",
            "owning_user_id",
            "github_user_id",
            "github_login",
            "credential_version",
            "identity_verified_at",
        }
    )
    CANDIDATE_FIELDS = frozenset(
        {"installation_id", "account_name", "account_type", "source_team_id", "source_team_name"}
    )
    FILTERED_FIELDS = frozenset({"installation_id", "source", "reason"})
    RESPONSE_FIELDS = frozenset(
        {
            "discovery_id",
            "discovered_at",
            "personal_github_connected",
            "personal_github_login",
            "personal_discovery_status",
        }
    )
    # Organizations with many GitHub projects would otherwise grow each discovery record without bound.
    MAX_RECORDED_INSTALLATIONS = 50
    # Discovery runs on every suggestions load and window focus, so it goes to logs only, not the activity log.
    LOG_ONLY_EVENTS = frozenset(
        {
            "discovery_credential_selected",
            "discovery_github_response",
            "discovery_candidates",
            "discovery_candidates_filtered",
            "discovery_completed",
            "discovery_failed",
        }
    )
    EVENT_FIELDS = {
        "created": {"outcome"},
        "deleted": {"outcome"},
        "credential_created": {"reason"},
        "credential_replaced": {"reason"},
        "credential_refreshed": {"reason"},
        "credential_deleted": {"reason"},
        "credential_delete_failed": {"failure_type"},
        "discovery_credential_selected": {"discovery_id", *PERSONAL_FIELDS},
        "discovery_github_response": {"discovery_id", "github_status", "github_request_id"},
        "discovery_candidates": {"discovery_id", "source"},
        "discovery_candidates_filtered": {"discovery_id"},
        "discovery_completed": {"discovery_id"},
        "discovery_failed": {"discovery_id", "reason"},
        "link_started": {"discovery_id", "installation_id", "path"},
        "link_path": {"discovery_id", "path", "source_team_id"},
        "link_completed": {"discovery_id", "installation_id", "path", "linked_integration_id"},
        "link_rejected": {"discovery_id", "installation_id", "path"},
        "link_failed": {"discovery_id", "installation_id", "failure_type"},
        "disconnect_started": {"last_reference"},
        "disconnect_failed": {"stage", "failure_type"},
        "uninstall_completed": {"outcome", "reason", "failure_type"},
        "personal_cleanup_failed": {"failure_type"},
        "webhook_cleanup": {"outcome", "completed_deletion"},
        "webhook_cleanup_failed": {"stage", "failure_type"},
        "setup_failed": {"flow_id", "callback_type"},
    }

    @staticmethod
    def fields(value: object, allowed: set[str] | frozenset[str]) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {
            key: item
            for key, item in value.items()
            if key in allowed and (item is None or isinstance(item, (str, int, float, bool)))
        }

    @classmethod
    def candidates(cls, value: object, allowed: frozenset[str] | None = None) -> list[dict[str, Any]]:
        allowed = allowed or cls.CANDIDATE_FIELDS
        return [cls.fields(item, allowed) for item in value] if isinstance(value, list) else []

    @classmethod
    def capped(cls, entries: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
        return len(entries), entries[: cls.MAX_RECORDED_INSTALLATIONS]

    @classmethod
    def error_codes(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, list):
            return [code for item in value for code in cls.error_codes(item)]
        return []

    @classmethod
    def evidence(cls, event: str, value: dict[str, Any]) -> dict[str, Any]:
        result = cls.fields(value, cls.EVENT_FIELDS.get(event, set()))
        if event == "discovery_candidates":
            result["candidates"] = cls.candidates(value.get("candidates"))
        elif event == "discovery_candidates_filtered":
            result["filtered_count"], result["filtered"] = cls.capped(
                cls.candidates(value.get("filtered"), cls.FILTERED_FIELDS)
            )
        elif event == "discovery_completed":
            response = value.get("response")
            result["response"] = cls.fields(response, cls.RESPONSE_FIELDS)
            if isinstance(response, dict):
                result["response"]["installation_count"], result["response"]["installations"] = cls.capped(
                    cls.candidates(response.get("installations"))
                )
        elif event in {"link_rejected", "setup_failed"}:
            field = "rejection_reason" if event == "link_rejected" else "failure_category"
            result[field] = cls.error_codes(value.get(field))
        return result


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
            **GitHubAuditPayload.fields(self.personal_metadata, GitHubAuditPayload.PERSONAL_FIELDS),
            **GitHubAuditPayload.evidence(event, evidence),
        }

        def write() -> None:
            logger.info(
                event,
                organization_id=str(self.organization_id) if self.organization_id else None,
                team_id=self.team_id,
                actor_id=self.user.pk if self.user else None,
                **payload,
            )
            if self.organization_id is None or event in GitHubAuditPayload.LOG_ONLY_EVENTS:
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
                                job_id=str(payload.get("discovery_id") or ""),
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
