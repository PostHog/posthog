"""The opt-in AI scan for ticket patterns.

Conversations owns no AI here. Turning the scan on stands up a Signals scout for the project from a
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
from posthog.models import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.conversations.backend.temporal.patterns.eligibility import is_pattern_detection_enabled
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
    scope_object_read_actions = ["status", "reports"]
    scope_object_write_actions = ["create", "disable"]
    serializer_class = AiScanStatusSerializer

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Turning the scan on creates a skill and a scout config, so a token needs those scopes too,
        # not only the ticket one the mixin derives.
        if self.action in ("create", "disable"):
            return ["ticket:write", "llm_skill:write", "signal_scout:write"]
        return None

    @property
    def _scout_team(self) -> Team:
        # Scouts are project-level objects: Signals stores them on the canonical team. Every read
        # and write here has to use that same team, or an environment's request stamps a scout
        # the rest of the project cannot find.
        return self.team.parent_team or self.team

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

    def _existing(self) -> signals_facade.ScoutForSource | None:
        team = self._scout_team
        return signals_facade.scout_for_source(team.id, SCOUT_SOURCE_PRODUCT, str(team.id))

    def _status(self) -> dict[str, Any]:
        scout = self._existing()
        return {
            "enabled": scout is not None and scout.enabled and scout.skill_exists,
            "scout_config_id": scout.config_id if scout else None,
            "skill_name": scout.skill_name if scout and scout.skill_exists else None,
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
            409: OpenApiResponse(description="Ticket pattern detection is off for this project."),
        },
        description=(
            "Turn the AI scan on: create the ticket patterns scout for this project from the canonical skill, "
            "or resume it and bring its skill up to the current canonical definition."
        ),
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        self._assert_can_write()
        if not self.team.organization.is_ai_data_processing_approved:
            raise exceptions.PermissionDenied(
                "AI data processing is not approved for this organization. An admin can approve it in organization settings."
            )
        if not is_pattern_detection_enabled(self.team):
            raise exceptions.ValidationError(
                {"detail": "Turn on ticket pattern detection first. The AI scan reads the patterns it opens."},
                code="detection_disabled",
            )
        team = self._scout_team
        user = cast("User", request.user)
        description, body = canonical_scout_definition()
        existing = self._existing()
        if existing is not None and existing.skill_exists:
            signals_facade.sync_scout_definition_for_source(
                team=team,
                user=user,
                source_product=SCOUT_SOURCE_PRODUCT,
                config_id=existing.config_id,
                description=description,
                body=body,
            )
            if not existing.enabled:
                signals_facade.update_scout_for_source(team.id, SCOUT_SOURCE_PRODUCT, existing.config_id, enabled=True)
            return Response(AiScanStatusSerializer(self._status()).data, status=status.HTTP_200_OK)

        result = signals_facade.create_scout_for_source(
            team=team,
            user=user,
            name=SCOUT_SKILL_NAME,
            description=description,
            body=body,
            files=[],
            config_options={
                "enabled": True,
                "emit": True,
                "run_interval_minutes": SCOUT_RUN_INTERVAL_MINUTES,
                # Findings are read on the Patterns tab, which the Inbox's inactivity sweep cannot
                # see, so without this it would pause the scan as ignored.
                "auto_pause_exempt": True,
            },
            request=request,
            serializer_context={"project_id": self.team.project_id, "team": team, "request": request},
            source_product=SCOUT_SOURCE_PRODUCT,
            source_id=str(team.id),
        )
        return Response(
            AiScanStatusSerializer(self._status()).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(response=AiScanStatusSerializer, description="The scan is off.")},
        description="Turn the AI scan off. The scout is paused, not deleted, so its memory and reports survive.",
    )
    @action(methods=["POST"], detail=False)
    def disable(self, request: Request, **kwargs: Any) -> Response:
        self._assert_can_write()
        existing = self._existing()
        if existing is not None:
            signals_facade.update_scout_for_source(
                self._scout_team.id, SCOUT_SOURCE_PRODUCT, existing.config_id, enabled=False
            )
        return Response(AiScanStatusSerializer(self._status()).data, status=status.HTTP_200_OK)

    @extend_schema(
        responses=AiScanReportSerializer(many=True),
        description=(
            "What the AI scan has found, newest first. Turning the scan off keeps its past findings, so this "
            "still answers for a paused scan. Empty when the scan has never run or has found nothing."
        ),
    )
    @action(methods=["GET"], detail=False)
    def reports(self, request: Request, **kwargs: Any) -> Response:
        self._assert_can_read()
        team = self._scout_team
        reports = signals_facade.scout_reports_for_source(
            team.id, SCOUT_SOURCE_PRODUCT, str(team.id), limit=MAX_REPORTS
        )
        return Response(AiScanReportSerializer(reports, many=True).data)
