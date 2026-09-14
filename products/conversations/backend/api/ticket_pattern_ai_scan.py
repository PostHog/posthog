"""The opt-in AI scan for ticket patterns.

Conversations owns no AI here. Turning the scan on stands up a Signals scout for the team from a
canonical skill shipped with this product, stamped `(source_product="conversations", source_id=<team>)`
so Signals knows who it belongs to. Signals runs it, bills it, and files its reports; this module is
the toggle and the read path that shows those reports beside the detector's own patterns.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.facade import api as signals_facade

if TYPE_CHECKING:
    from posthog.models import User

SCOUT_SOURCE_PRODUCT = "conversations"
SCOUT_SKILL_NAME = "signals-scout-ticket-patterns"
SCOUT_RUN_INTERVAL_MINUTES = 60
MAX_REPORTS = 50

_SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / SCOUT_SKILL_NAME / "SKILL.md"


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.index("\n---\n", 4)
    return text[4:end], text[end + 5 :]


def canonical_scout_definition() -> tuple[str, str]:
    """(description, body) from the skill shipped in this product's `skills/` tree."""
    frontmatter, body = _split_frontmatter(_SKILL_PATH.read_text())
    description_lines: list[str] = []
    capturing = False
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            capturing = True
            continue
        if capturing:
            if line.startswith("  "):
                description_lines.append(line.strip())
            else:
                break
    return " ".join(description_lines), body.strip() + "\n"


class AiScanStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="Whether an AI scan scout exists and is running for this project.")
    scout_config_id = serializers.CharField(
        allow_null=True, help_text="The Signals scout config behind the scan, for linking into the Inbox."
    )
    skill_name = serializers.CharField(allow_null=True, help_text="The scout's skill name in the Skills store.")
    last_run_at = serializers.DateTimeField(allow_null=True, help_text="When the scout last ran.")
    ai_consent_granted = serializers.BooleanField(
        help_text="Whether the organization has approved AI data processing. The scan cannot be turned on without it."
    )


class AiScanReportSerializer(serializers.Serializer):
    report_id = serializers.CharField(help_text="Signals report id, for linking into the Inbox.")
    title = serializers.CharField(help_text="Report title, written by the scout.")
    summary = serializers.CharField(help_text="Report summary, written by the scout. Ticket links are inside it.")
    filed_at = serializers.DateTimeField(help_text="When the scout run that filed this report started.")


class TicketPatternAiScanViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Turn the AI scan on or off, read its state, and read what it has found.

    Same all-or-nothing ticket gate as patterns. Turning the scan on additionally needs skill editor
    access, which the Signals facade checks itself, because a scout is a skill.
    """

    scope_object = "ticket"
    scope_object_write_actions = ["create", "disable"]
    serializer_class = AiScanStatusSerializer

    def _access(self) -> UserAccessControl:
        return cast(UserAccessControl, self.user_access_control)

    def _assert_can_read(self) -> None:
        uac = self._access()
        if bool(uac.blocked_resource_ids_by_scope.get("ticket")) or not uac.has_resource_access("ticket"):
            raise exceptions.PermissionDenied("You need access to every ticket to see the AI scan.")

    def _assert_can_write(self) -> None:
        self._assert_can_read()
        if not self._access().check_access_level_for_resource("ticket", "editor"):
            raise exceptions.PermissionDenied("You need edit access to every ticket to change the AI scan.")

    def _status(self) -> dict[str, Any]:
        scout = signals_facade.scout_for_source(self.team_id, SCOUT_SOURCE_PRODUCT, str(self.team_id))
        return {
            "enabled": scout is not None and scout.enabled,
            "scout_config_id": scout.config_id if scout else None,
            "skill_name": scout.skill_name if scout else None,
            "last_run_at": scout.last_run_at if scout else None,
            "ai_consent_granted": bool(self.team.organization.is_ai_data_processing_approved),
        }

    @extend_schema(responses=AiScanStatusSerializer, description="Whether the AI scan is on for this project.")
    @action(methods=["GET"], detail=False)
    def status(self, request: Request, **kwargs: Any) -> Response:
        self._assert_can_read()
        return Response(AiScanStatusSerializer(self._status()).data)

    @extend_schema(
        request=None,
        responses={
            201: OpenApiResponse(response=AiScanStatusSerializer, description="The scout was created."),
            200: OpenApiResponse(response=AiScanStatusSerializer, description="The scout already existed."),
            403: OpenApiResponse(description="No AI consent, or the caller may not edit tickets."),
        },
        description="Turn the AI scan on: create the ticket patterns scout for this project from the canonical skill.",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        self._assert_can_write()
        if not self.team.organization.is_ai_data_processing_approved:
            raise exceptions.PermissionDenied(
                "AI data processing is not approved for this organization. An admin can approve it in organization settings."
            )
        existing = signals_facade.scout_for_source(self.team_id, SCOUT_SOURCE_PRODUCT, str(self.team_id))
        if existing is not None:
            if not existing.enabled:
                signals_facade.update_scout_for_source(
                    self.team_id, SCOUT_SOURCE_PRODUCT, existing.config_id, enabled=True
                )
            return Response(AiScanStatusSerializer(self._status()).data, status=status.HTTP_200_OK)

        description, body = canonical_scout_definition()
        canonical_team = self.team.parent_team or self.team
        result = signals_facade.create_scout_for_source(
            team=canonical_team,
            user=cast("User", request.user),
            name=SCOUT_SKILL_NAME,
            description=description,
            body=body,
            files=[],
            config_options={"enabled": True, "emit": True, "run_interval_minutes": SCOUT_RUN_INTERVAL_MINUTES},
            request=request,
            serializer_context={"project_id": self.team.project_id, "team": canonical_team, "request": request},
            source_product=SCOUT_SOURCE_PRODUCT,
            source_id=str(self.team_id),
        )
        return Response(
            AiScanStatusSerializer(self._status()).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="The scan is off.")},
        description="Turn the AI scan off. The scout is paused, not deleted, so its memory and reports survive.",
    )
    @action(methods=["POST"], detail=False)
    def disable(self, request: Request, **kwargs: Any) -> Response:
        self._assert_can_write()
        existing = signals_facade.scout_for_source(self.team_id, SCOUT_SOURCE_PRODUCT, str(self.team_id))
        if existing is not None and existing.enabled:
            signals_facade.update_scout_for_source(
                self.team_id, SCOUT_SOURCE_PRODUCT, existing.config_id, enabled=False
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        responses=AiScanReportSerializer(many=True),
        description=(
            "What the AI scan has found, newest first. Turning the scan off pauses the scout, so its past "
            "findings stay in this list. Empty when nothing has been found."
        ),
    )
    @action(methods=["GET"], detail=False)
    def reports(self, request: Request, **kwargs: Any) -> Response:
        self._assert_can_read()
        reports = signals_facade.scout_reports_for_source(
            self.team_id, SCOUT_SOURCE_PRODUCT, str(self.team_id), limit=MAX_REPORTS
        )
        return Response(AiScanReportSerializer(reports, many=True).data)
