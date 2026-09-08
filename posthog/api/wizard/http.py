from __future__ import annotations

import time
from typing import NoReturn, cast

from django.conf import settings
from django.core.cache import cache

import posthoganalytics
from drf_spectacular.utils import extend_schema
from prometheus_client import Counter
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, SessionAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.llm.wizard_blocklist import WIZARD_BLOCKED_DETAIL, wizard_identity_blocked
from posthog.llm.wizard_gateway_token import (
    WizardGatewayMintError,
    mint_wizard_gateway_token,
    wizard_gateway_base_url,
    wizard_gateway_configured,
    wizard_limit_override,
    wizard_product_node,
)
from posthog.models import Team, User
from posthog.models.project import Project
from posthog.rate_limit import (
    SetupWizardCloudRunBurstRateThrottle,
    SetupWizardCloudRunSustainedRateThrottle,
    SetupWizardGatewayTokenRateThrottle,
    refund_wizard_mint,
    reserve_wizard_mint,
)
from posthog.storage.gateway_credential_cache import (
    GATEWAY_CREDENTIAL_REQUIRED_SCOPE as RequiredGatewayScope,
    oauth_credential_authorized,
)
from posthog.user_permissions import UserPermissions

from products.tasks.backend.facade import api as tasks_facade

ERROR_PROJECT_NOT_FOUND = "This project does not exist."

# Absolute ceiling on sandbox boots per user per day, reserved atomically right before run
# creation. The DB-counted throttles above the view are read-then-create and can be raced by
# parallel requests; this cache.incr cannot, so it is the hard bound a start-cancel or crash
# loop lands on. Only requests that reach creation consume it.
WIZARD_CLOUD_RUN_DAILY_ATTEMPT_CAP = 15

WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL = Counter(
    "posthog_wizard_gateway_token_requests_total",
    "Wizard gateway-token mint requests, by outcome (minted/unconfigured/not_wizard_app/"
    "scope_missing/team_ambiguous/team_missing/unauthorized/blocked/program_unknown/"
    "not_rolled_out/mint_failed)",
    labelnames=["outcome"],
)

WIZARD_CLOUD_RUN_REQUESTS_TOTAL = Counter(
    "posthog_wizard_cloud_run_requests_total",
    "Cloud-run wizard kickoff requests, by outcome (created/unavailable/invalid/permission_denied/throttled)",
    labelnames=["outcome"],
)


class SetupWizardCloudRunSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(
        help_text="ID of the PostHog project to integrate PostHog into. The authenticated user must have access to it."
    )
    repository = serializers.CharField(
        help_text=(
            "GitHub repository to set up PostHog in, as 'owner/repo' (e.g. 'posthog/posthog-js'). The user "
            "must have a connected GitHub integration with access to it."
        )
    )
    branch = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Base branch the wizard's pull request should target. Defaults to the repository's default branch.",
    )

    def validate_repository(self, value: str) -> str:
        repository = value.strip()
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts):
            raise serializers.ValidationError("Repository must be in 'owner/repo' format.")
        return repository


class SetupWizardCloudRunResponseSerializer(serializers.Serializer):
    task_id = serializers.CharField(
        help_text="ID of the created task. Poll the tasks API for its status and the resulting pull request URL."
    )
    run_id = serializers.CharField(help_text="ID of the task's run.")
    status = serializers.CharField(help_text="Initial status of the run (e.g. 'queued').")


class SetupWizardViewSet(viewsets.ViewSet):
    permission_classes = ()

    def throttled(self, request: Request, wait: float) -> NoReturn:
        # A rejection from DRF's own throttle check returns before the action body, so
        # it counts here. A reservation that raises inside a body counts there instead.
        if self.action == "cloud_run":
            WIZARD_CLOUD_RUN_REQUESTS_TOTAL.labels(outcome="throttled").inc()
        if self.action == "gateway_token":
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="throttled").inc()
        super().throttled(request, wait)

    @action(
        methods=["POST"],
        detail=False,
        url_path="gateway_token",
        throttle_classes=[SetupWizardGatewayTokenRateThrottle],
    )
    def gateway_token(self, request: Request) -> Response:
        """Mint a scoped gateway token for a wizard run.

        The CLI uses the returned phe_ (pinned product=wizard / obo=<customer org>,
        capped, expiring) as its gateway bearer and re-calls near expiry. It treats
        a 404 as "stay on the legacy gateway", so rollout is controlled here rather
        than by a CLI release. Every other failure fails the run.
        """
        if not wizard_gateway_configured():
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="unconfigured").inc()
            raise exceptions.NotFound("Wizard gateway tokens are not available.")

        authenticator = OAuthAccessTokenAuthentication()
        # authenticate() raises its own AuthenticationFailed, so the count wraps the
        # call rather than only the two checks below.
        try:
            result = authenticator.authenticate(request)
            if not result:
                raise AuthenticationFailed("Invalid access token.")
            user, _ = result
            if not user:
                raise AuthenticationFailed("Invalid access token.")
        except AuthenticationFailed:
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="invalid_token").inc()
            raise

        access_token = authenticator.access_token
        # llm_gateway:read is on every sandbox and agent token, so the scope alone
        # cannot identify the wizard.
        application = getattr(access_token, "application", None)
        client_id = getattr(application, "client_id", None)
        if not client_id or client_id not in settings.WIZARD_GATEWAY_CLIENT_IDS:
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="not_wizard_app").inc()
            raise AuthenticationFailed("Access token was not issued to the wizard.")

        # The token's own scope text: the `scopes` property filters through
        # OAUTH2_PROVIDER["SCOPES"], where a narrowing would silently drop the scope.
        if RequiredGatewayScope not in (access_token.scope or "").split():
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="scope_missing").inc()
            raise AuthenticationFailed("Access token lacks the gateway scope.")

        scoped_team_ids = access_token.scoped_teams or []
        if len(scoped_team_ids) != 1:
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="team_ambiguous").inc()
            raise exceptions.ValidationError("Access token must be scoped to exactly one team.")
        team = Team.objects.select_related("organization").filter(id=scoped_team_ids[0]).first()
        if team is None:
            # Deliberately 403: a 404 would read as "not rolled out" and downgrade
            # the run to legacy, but a vanished team is an authorization failure.
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="team_missing").inc()
            raise exceptions.PermissionDenied(ERROR_PROJECT_NOT_FOUND)

        # scoped_teams is frozen at consent, so re-check what it cannot see.
        if not oauth_credential_authorized(access_token, team):
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="unauthorized").inc()
            raise exceptions.PermissionDenied("Access token is no longer authorized for this project.")

        distinct_id = str(user.distinct_id)
        if wizard_identity_blocked(
            distinct_id=distinct_id,
            email=user.email,
            user_uuid=str(user.uuid),
            organization_ids=[str(team.organization_id)],
            team_ids=[team.id],
            surface="gateway_token",
        ):
            # 403 and not 404, ahead of the rollout gate: the CLI reads 404 as "stay
            # on legacy", moving a banned run onto the looser surface.
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="blocked").inc()
            raise exceptions.PermissionDenied(WIZARD_BLOCKED_DETAIL)

        if not posthoganalytics.feature_enabled(
            "wizard-gateway-v2",
            distinct_id,
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        ):
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="not_rolled_out").inc()
            raise exceptions.NotFound("Wizard gateway tokens are not rolled out for this organization.")

        # Refusing keeps every pinned node one that carries a budget.
        product = wizard_product_node(request.data.get("program") if isinstance(request.data, dict) else None)
        if product is None:
            # 404 and not 400: the CLI falls back only on 404, so an unlisted
            # program keeps running on legacy instead of dying. It still cannot mint.
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="program_unknown").inc()
            raise exceptions.NotFound("Unrecognized wizard program.")
        override = wizard_limit_override(
            distinct_id=distinct_id,
            email=user.email,
            organization_id=str(team.organization_id),
            team_id=team.id,
        )
        try:
            reserved = reserve_wizard_mint(request, self, limit=override.mints_per_day)
        except exceptions.Throttled:
            # The reservation raises after check_throttles ran, so the throttled()
            # hook never sees it.
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="throttled").inc()
            raise
        try:
            minted = mint_wizard_gateway_token(
                obo=str(team.organization_id), user=distinct_id, product=product, cap_usd=override.cap_usd
            )
        except WizardGatewayMintError as e:
            # An ambiguous failure keeps the slot rather than risk the ceiling.
            if not e.token_may_exist:
                refund_wizard_mint(reserved)
            WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="mint_failed").inc()
            capture_exception(e, {"ai_product": "wizard", "team_id": team.id})
            return Response({"error": "Gateway token mint failed."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        WIZARD_GATEWAY_TOKEN_REQUESTS_TOTAL.labels(outcome="minted").inc()
        return Response(
            {
                "token": minted["token"],
                "expires_at": minted["expires_at"],
                "cap_usd": minted.get("cap_usd"),
                "gateway_url": wizard_gateway_base_url(),
                # Keeps a team breakdown beside the org-level obo attribution.
                "team_id": team.id,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=SetupWizardCloudRunSerializer,
        responses={200: SetupWizardCloudRunResponseSerializer},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="cloud_run",
        authentication_classes=[SessionAuthentication],
        permission_classes=[IsAuthenticated],
        throttle_classes=[
            SetupWizardCloudRunBurstRateThrottle,
            SetupWizardCloudRunSustainedRateThrottle,
        ],
    )
    def cloud_run(self, request: Request) -> Response:
        """Run the PostHog setup wizard in the cloud against the user's GitHub repository.

        Provisions a task-run sandbox that runs the published wizard headlessly to integrate PostHog,
        then hands off to the task agent to open the pull request and keep it green. The wizard
        authenticates with a dedicated, scoped token minted under the wizard's own OAuth app — distinct
        from the agent's sandbox token. This is the cloud alternative to copy-pasting the wizard command
        to run locally; it is intentionally rate limited heavily because each run starts a sandbox.
        """
        try:
            response = self._cloud_run(request)
        except exceptions.NotFound:
            WIZARD_CLOUD_RUN_REQUESTS_TOTAL.labels(outcome="unavailable").inc()
            raise
        except exceptions.PermissionDenied:
            WIZARD_CLOUD_RUN_REQUESTS_TOTAL.labels(outcome="permission_denied").inc()
            raise
        except exceptions.ValidationError:
            WIZARD_CLOUD_RUN_REQUESTS_TOTAL.labels(outcome="invalid").inc()
            raise
        except exceptions.Throttled:
            # The atomic attempt reservation inside _cloud_run raises after check_throttles
            # ran, so the throttled() hook below never sees it.
            WIZARD_CLOUD_RUN_REQUESTS_TOTAL.labels(outcome="throttled").inc()
            raise
        WIZARD_CLOUD_RUN_REQUESTS_TOTAL.labels(outcome="created").inc()
        return response

    @staticmethod
    def _reserve_cloud_run_attempt(user_id: int) -> None:
        """Atomically consume one of the user's daily cloud-run attempts or raise Throttled.

        Runs after validation and project access checks, immediately before run creation, so
        rejected requests never consume the budget — while parallel requests cannot all slip
        under the ceiling the way they can with the read-then-create DB throttles.
        """
        window = int(time.time()) // 86400
        key = f"wizard_cloud_run_attempts:{user_id}:{window}"
        cache.add(key, 0, timeout=86400)
        try:
            count = cache.incr(key)
        except ValueError:
            # The key expired between add and incr; this request is the window's first.
            count = 1
        if count > WIZARD_CLOUD_RUN_DAILY_ATTEMPT_CAP:
            raise exceptions.Throttled(detail="You've reached today's limit for cloud setup runs. Try again tomorrow.")

    def _cloud_run(self, request: Request) -> Response:
        if not bool(settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID):
            raise exceptions.NotFound("Running the setup wizard in the cloud is not available.")

        serializer = SetupWizardCloudRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project_id = serializer.validated_data["project_id"]
        repository = serializer.validated_data["repository"]
        branch = serializer.validated_data.get("branch") or None

        visible_project_ids = UserPermissions(cast(User, request.user)).project_ids_visible_for_user
        try:
            # nosemgrep: idor-lookup-without-org, idor-taint-user-input-to-org-model (permission check below)
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            raise serializers.ValidationError({"project_id": [ERROR_PROJECT_NOT_FOUND]}, code="not_found")
        if project.id not in visible_project_ids:
            raise exceptions.PermissionDenied("You don't have access to this project.")

        user = cast(User, request.user)
        # The sandbox this starts mints its own gateway token. Refused before the
        # attempt is reserved, so a ban does not also cost a daily slot.
        if wizard_identity_blocked(
            distinct_id=str(user.distinct_id),
            email=user.email,
            user_uuid=str(user.uuid),
            organization_ids=[str(project.organization_id)],
            team_ids=[project.id],
            surface="cloud_run",
        ):
            # No outcome label: `cloud_run` already counts every PermissionDenied as
            # permission_denied.
            raise exceptions.PermissionDenied(WIZARD_BLOCKED_DETAIL)

        self._reserve_cloud_run_attempt(user.id)

        try:
            result = tasks_facade.create_wizard_cloud_run(
                team=project.passthrough_team,
                user_id=cast(User, request.user).id,
                repository=repository,
                branch=branch,
            )
        except ValueError as e:
            # e.g. the team/user has no GitHub integration with access to the repository.
            raise exceptions.ValidationError(str(e))

        latest_run = result.latest_run
        return Response(
            {
                "task_id": str(result.task_id),
                "run_id": str(latest_run.id) if latest_run else "",
                "status": latest_run.status if latest_run else "queued",
            }
        )
