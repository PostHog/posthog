"""CI trust policies: which repository's CI jobs may exchange an OIDC token for a project token.

A policy hands out tokens that act as the organization owner, so it is a standing credential. Members
can read policies. Only an organization admin or owner can write one, and only from a browser session
with recent authentication, so no token can create or widen a policy.
"""

import functools
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.oauth.ci_providers import (
    get_ci_provider_by_issuer,
    get_supported_ci_providers,
    get_unsupported_ci_providers,
    normalize_issuer,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models import OrganizationMembership, Team, User
from posthog.models.ci_trust_policy import (
    CITrustPolicy,
    CITrustPolicyRequest,
    ci_trust_policy_grantable_scopes,
    ci_trust_policy_request_url,
    ci_trust_policy_scopes_not_grantable,
)
from posthog.organization_caching import get_cached_organization_membership
from posthog.permissions import (
    OrganizationAdminWritePermissions,
    TimeSensitiveActionPermission,
    get_organization_from_view,
    get_required_organization_membership,
)
from posthog.rate_limit import CITrustPolicyRequestBurstThrottle, CITrustPolicyRequestSustainedThrottle
from posthog.tasks.email import CITrustPolicyChange, send_ci_trust_policy_changed

# A policy matches claim values exactly, so a character that reads as a pattern is refused rather than
# taken literally: an admin who types `acme/*` expects every repository to match, and none would.
WILDCARD_CHARACTERS = frozenset("*?[]")
DUPLICATE_POLICY_MESSAGE = "A policy with the same issuer, repository, ref and environment exists."


def _validate_exact_value(value: str, field_label: str) -> str:
    stripped = value.strip()
    if stripped != value:
        raise serializers.ValidationError(f"{field_label} must not start or end with whitespace.")
    if any(character in WILDCARD_CHARACTERS for character in value):
        raise serializers.ValidationError(f"{field_label} must be an exact value. Wildcards are not supported.")
    return value


def validate_ci_trust_conditions(attrs: dict[str, Any], *, partial_instance: Any | None = None) -> dict[str, Any]:
    """Shared by policies and policy requests, so both enforce the same conditions."""

    def current(field: str) -> Any:
        if field in attrs:
            return attrs[field]
        return getattr(partial_instance, field, "") if partial_instance is not None else ""

    if not current("ref") and not current("environment"):
        raise serializers.ValidationError(
            {"ref": "Set a ref, an environment, or both, so the policy does not match every job in the repository."}
        )
    return attrs


class CIScopeListField(serializers.ListField):
    child = serializers.CharField(max_length=100)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(allow_empty=False, **kwargs)

    def to_internal_value(self, data: Any) -> list[str]:
        scopes = super().to_internal_value(data)
        not_grantable = ci_trust_policy_scopes_not_grantable(scopes)
        if not_grantable:
            raise serializers.ValidationError(
                f"These scopes can't be granted to CI jobs: {', '.join(not_grantable)}. "
                "A CI token can't manage credentials or access, and can't use privileged or hidden scopes."
            )
        return sorted(set(scopes))


class CIConditionsSerializerMixin(serializers.Serializer):
    issuer = serializers.CharField(
        max_length=255,
        help_text="The OIDC issuer of the CI provider, from the list of supported providers.",
    )
    provider = serializers.SerializerMethodField(help_text="The key of the CI provider the issuer belongs to.")
    repository = serializers.CharField(
        max_length=255, help_text="The repository's full name, for example `acme/web`. Matched exactly."
    )
    repository_id = serializers.CharField(
        max_length=100,
        help_text=(
            "The repository's immutable ID from the CI provider. Matched together with the name, so a deleted "
            "and re-created repository with the same name does not match."
        ),
    )
    ref = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="The git ref the job must run on, for example `refs/heads/main`. Empty matches any ref.",
    )
    environment = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text="The deployment environment the job must run in. Empty matches any environment.",
    )

    def get_provider(self, instance: CITrustPolicy | CITrustPolicyRequest) -> str | None:
        provider = get_ci_provider_by_issuer(instance.issuer)
        return provider.key if provider else None

    def validate_issuer(self, value: str) -> str:
        provider = get_ci_provider_by_issuer(value)
        if provider is None:
            raise serializers.ValidationError("This issuer isn't a supported CI provider.")
        return normalize_issuer(provider.issuer)

    def validate_repository(self, value: str) -> str:
        return _validate_exact_value(value, "Repository")

    def validate_repository_id(self, value: str) -> str:
        return _validate_exact_value(value, "Repository ID")

    def validate_ref(self, value: str) -> str:
        return _validate_exact_value(value, "Ref")

    def validate_environment(self, value: str) -> str:
        return _validate_exact_value(value, "Environment")


class CITrustPolicySerializer(CIConditionsSerializerMixin, serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, help_text="A name that says what the policy is for.")
    scopes = CIScopeListField(
        help_text=(
            "The scopes every token minted under this policy carries. Scopes that manage credentials or access "
            "are refused."
        )
    )
    enabled = serializers.BooleanField(
        required=False, help_text="Whether the policy can mint tokens. Disabling it cuts off its tokens."
    )
    created_by = UserBasicSerializer(read_only=True, allow_null=True)

    class Meta:
        model = CITrustPolicy
        fields = [
            "id",
            "name",
            "issuer",
            "provider",
            "repository",
            "repository_id",
            "ref",
            "environment",
            "scopes",
            "enabled",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "provider", "created_by", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = validate_ci_trust_conditions(attrs, partial_instance=self.instance)
        team = cast(Team, self.context["get_team"]())
        conditions = {
            field: attrs.get(field, getattr(self.instance, field, ""))
            for field in ("issuer", "repository_id", "ref", "environment")
        }
        clash = CITrustPolicy.objects.filter(**conditions)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(DUPLICATE_POLICY_MESSAGE)
        attrs["team"] = team
        return attrs

    def create(self, validated_data: dict[str, Any]) -> CITrustPolicy:
        try:
            return super().create(validated_data)
        except IntegrityError:
            # Two writes with the same conditions can both pass the check in `validate`.
            raise serializers.ValidationError(DUPLICATE_POLICY_MESSAGE)

    def update(self, instance: CITrustPolicy, validated_data: dict[str, Any]) -> CITrustPolicy:
        try:
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError(DUPLICATE_POLICY_MESSAGE)


class CIProviderClaimsSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Claim that carries the repository's full name.")
    repository_id = serializers.CharField(help_text="Claim that carries the repository's immutable ID.")
    ref = serializers.CharField(allow_null=True, help_text="Claim that carries the git ref, or null.")
    environment = serializers.CharField(allow_null=True, help_text="Claim that carries the environment, or null.")


class CIProviderSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable identifier of the provider.")
    name = serializers.CharField(help_text="Display name of the provider.")
    issuer = serializers.CharField(help_text="OIDC issuer a policy for this provider uses.")
    docs_url = serializers.CharField(help_text="Where to read how to set the provider up.")
    claims = CIProviderClaimsSerializer(help_text="Which token claims a policy matches on.")


class UnsupportedCIProviderSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable identifier of the provider.")
    name = serializers.CharField(help_text="Display name of the provider.")
    reason = serializers.CharField(help_text="Why the provider can't be used.")


class CIProvidersResponseSerializer(serializers.Serializer):
    supported = CIProviderSerializer(many=True, help_text="Providers a policy can trust.")
    unsupported = UnsupportedCIProviderSerializer(many=True, help_text="Known providers that can't be trusted.")
    grantable_scopes = serializers.ListField(
        child=serializers.CharField(), help_text="Every scope a policy's ceiling may hold."
    )


def notify_admins_of_policy_change(
    team_id: int, policy_id: str, name: str, change: CITrustPolicyChange, actor_user_id: int | None
) -> None:
    transaction.on_commit(lambda: send_ci_trust_policy_changed.delay(team_id, policy_id, name, change, actor_user_id))


class NotImpersonatedWritePermission(BasePermission):
    """A policy is a standing credential that acts as the owner, so staff impersonating a member can read
    policies but not change them, or ask for them."""

    message = "CI trust policies act as the organization owner, so they can't be changed while impersonating a user."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.method in SAFE_METHODS or not is_impersonated(request)


class BrowserSessionWritePermission(BasePermission):
    """Writes need a browser session. Every token type gets a 403, because a token can only ask for a
    policy, which an admin then approves in the browser."""

    message = "CI trust policies can only be changed in the PostHog app, by an organization admin."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return isinstance(request.successful_authenticator, SessionAuthentication)


@extend_schema(extensions={"x-product": "core"})
class CITrustPolicyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "ci_trust_policy"
    queryset = CITrustPolicy.objects.unscoped()
    serializer_class = CITrustPolicySerializer
    lookup_field = "id"
    permission_classes = [
        BrowserSessionWritePermission,
        NotImpersonatedWritePermission,
        TimeSensitiveActionPermission,
        OrganizationAdminWritePermissions,
    ]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return CITrustPolicy.objects.all().select_related("created_by").order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        policy = serializer.save(created_by=self.request.user)
        notify_admins_of_policy_change(self.team_id, str(policy.pk), policy.name, "created", self.request.user.pk)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        policy = serializer.save()
        notify_admins_of_policy_change(self.team_id, str(policy.pk), policy.name, "updated", self.request.user.pk)

    def perform_destroy(self, instance: CITrustPolicy) -> None:
        policy_id, name = str(instance.pk), instance.name
        instance.delete()
        notify_admins_of_policy_change(self.team_id, policy_id, name, "deleted", self.request.user.pk)

    @extend_schema(responses={200: CIProvidersResponseSerializer})
    @action(methods=["GET"], detail=False, required_scopes=["ci_trust_policy:read"], pagination_class=None)
    def providers(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = {
            "supported": [
                {
                    "key": provider.key,
                    "name": provider.name,
                    "issuer": provider.issuer,
                    "docs_url": provider.docs_url,
                    "claims": {
                        "repository": provider.claims.repository,
                        "repository_id": provider.claims.repository_id,
                        "ref": provider.claims.ref,
                        "environment": provider.claims.environment,
                    },
                }
                for provider in get_supported_ci_providers()
            ],
            "unsupported": [
                {"key": provider.key, "name": provider.name, "reason": provider.reason}
                for provider in get_unsupported_ci_providers()
            ],
            "grantable_scopes": sorted(ci_trust_policy_grantable_scopes()),
        }
        return Response(CIProvidersResponseSerializer(payload).data)


def requested_via(request: Request) -> tuple[str, bool | None]:
    """The client a request came through, and whether PostHog verified it. Only an OAuth app has a
    verification state, so the second value is None for the other credentials."""
    authenticator = request.successful_authenticator
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        application = authenticator.access_token.application
        if application is None:
            return "an OAuth app", False
        return application.name, application.is_verified or application.is_first_party
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return "a personal API key", None
    if isinstance(authenticator, SessionAuthentication):
        return "the PostHog app", None
    return "an API token", None


class CITrustPolicyRequestSerializer(CIConditionsSerializerMixin, serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, help_text="The name the policy gets once approved.")
    provider_name = serializers.SerializerMethodField(help_text="The display name of the CI provider, or null.")
    scopes = CIScopeListField(help_text="The scopes the policy's tokens would carry.")
    status = serializers.SerializerMethodField(help_text="Where the request stands. A request expires after 7 days.")
    approval_url = serializers.SerializerMethodField(help_text="The link to send to an admin to approve the request.")
    can_approve = serializers.SerializerMethodField(
        help_text="Whether the current user's role lets them approve the request, in the browser."
    )
    approvers = serializers.SerializerMethodField(
        help_text="Names of the organization admins and owners who can approve, when the current user cannot."
    )
    requested_by = UserBasicSerializer(read_only=True)
    resolved_by = UserBasicSerializer(read_only=True)
    policy_id = serializers.UUIDField(read_only=True, allow_null=True, help_text="The policy created on approval.")

    class Meta:
        model = CITrustPolicyRequest
        fields = [
            "id",
            "name",
            "issuer",
            "provider",
            "provider_name",
            "repository",
            "repository_id",
            "ref",
            "environment",
            "scopes",
            "status",
            "approval_url",
            "can_approve",
            "approvers",
            "requested_by",
            "requested_via",
            "requested_via_verified",
            "created_at",
            "expires_at",
            "resolved_by",
            "resolved_at",
            "policy_id",
        ]
        read_only_fields = [
            "id",
            "provider",
            "provider_name",
            "status",
            "approval_url",
            "can_approve",
            "approvers",
            "requested_by",
            "requested_via",
            "requested_via_verified",
            "created_at",
            "expires_at",
            "resolved_by",
            "resolved_at",
            "policy_id",
        ]
        extra_kwargs = {
            "requested_via": {"help_text": "The client the request came through, for example hog."},
            "requested_via_verified": {
                "help_text": "Whether PostHog verified the OAuth app the request came through, or null for other clients."
            },
            "created_at": {"help_text": "When the request was made."},
            "expires_at": {"help_text": "When a pending request stops being approvable."},
            "resolved_at": {"help_text": "When an admin approved or rejected the request."},
        }

    def get_provider_name(self, policy_request: CITrustPolicyRequest) -> str | None:
        provider = get_ci_provider_by_issuer(policy_request.issuer)
        return provider.name if provider else None

    @extend_schema_field(serializers.ChoiceField(choices=CITrustPolicyRequest.Status.choices))
    def get_status(self, policy_request: CITrustPolicyRequest) -> str:
        return policy_request.effective_status

    def get_approval_url(self, policy_request: CITrustPolicyRequest) -> str:
        return ci_trust_policy_request_url(policy_request.team_id, str(policy_request.pk))

    def get_can_approve(self, policy_request: CITrustPolicyRequest) -> bool:
        return bool(self.context["can_approve"])

    def get_approvers(self, policy_request: CITrustPolicyRequest) -> list[str]:
        return [] if self.context["can_approve"] else self.context["approvers"]()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return validate_ci_trust_conditions(attrs)


class CITrustPolicyRequestResolutionPermission(BasePermission):
    """Approving or rejecting a request needs an organization admin or owner in a browser session. Asking
    for a policy is open to every member, so the check applies to the resolving actions only."""

    message = "Only an organization admin or owner can approve or reject a CI trust policy request, in the PostHog app."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) not in CITrustPolicyRequestViewSet.RESOLVING_ACTIONS:
            return True
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            return False
        membership = get_required_organization_membership(request, get_organization_from_view(view))
        return membership.level >= OrganizationMembership.Level.ADMIN


def resolve_ci_trust_policy_request(
    *, request_id: str, approve: bool, resolver: User, policy_serializer_context: dict[str, Any]
) -> CITrustPolicyRequest:
    """Approve or reject a pending request. Approving creates the policy from the request's own values,
    checked again against today's rules, in the same transaction that marks the request approved."""
    with transaction.atomic():
        policy_request = CITrustPolicyRequest.objects.select_for_update().get(pk=request_id)
        if policy_request.effective_status != CITrustPolicyRequest.Status.PENDING:
            raise serializers.ValidationError(f"This request is {policy_request.effective_status} and can't change.")
        if approve:
            policy_serializer = CITrustPolicySerializer(
                data={
                    field: getattr(policy_request, field)
                    for field in ("name", "issuer", "repository", "repository_id", "ref", "environment", "scopes")
                },
                context=policy_serializer_context,
            )
            policy_serializer.is_valid(raise_exception=True)
            policy_request.policy = policy_serializer.save(created_by=resolver)
        policy_request.status = (
            CITrustPolicyRequest.Status.APPROVED if approve else CITrustPolicyRequest.Status.REJECTED
        )
        policy_request.resolved_by = resolver
        policy_request.resolved_at = timezone.now()
        policy_request.save()
    return policy_request


@extend_schema(extensions={"x-product": "core"})
class CITrustPolicyRequestViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    RESOLVING_ACTIONS = frozenset({"approve", "reject"})

    scope_object = "ci_trust_policy_request"
    queryset = CITrustPolicyRequest.objects.unscoped()
    serializer_class = CITrustPolicyRequestSerializer
    lookup_field = "id"
    permission_classes = [
        NotImpersonatedWritePermission,
        TimeSensitiveActionPermission,
        CITrustPolicyRequestResolutionPermission,
    ]
    # Asking for a policy grants nothing, so it never needs a fresh login. Approving and rejecting do.
    time_sensitive_exclude_actions = ["create"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return CITrustPolicyRequest.objects.all().select_related("requested_by", "resolved_by").order_by("-created_at")

    def get_throttles(self) -> list[Any]:
        if self.action == "create":
            return [CITrustPolicyRequestBurstThrottle(), CITrustPolicyRequestSustainedThrottle()]
        return super().get_throttles()

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        organization_id = self.organization.id
        membership = get_cached_organization_membership(organization_id, cast(User, self.request.user))
        context["can_approve"] = membership is not None and membership.level >= OrganizationMembership.Level.ADMIN

        @functools.cache
        def approvers() -> list[str]:
            memberships = (
                OrganizationMembership.objects.filter(
                    organization_id=organization_id,
                    level__gte=OrganizationMembership.Level.ADMIN,
                    user__is_active=True,
                )
                .select_related("user")
                .order_by("-level", "joined_at")
            )
            return [membership.user.get_full_name() or membership.user.email for membership in memberships]

        context["approvers"] = approvers
        return context

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        via, via_verified = requested_via(self.request)
        serializer.save(
            team=self.team, requested_by=self.request.user, requested_via=via, requested_via_verified=via_verified
        )

    def _resolve(self, approve: bool) -> Response:
        policy_request = self.get_object()
        resolved = resolve_ci_trust_policy_request(
            request_id=str(policy_request.pk),
            approve=approve,
            resolver=cast(User, self.request.user),
            policy_serializer_context=self.get_serializer_context(),
        )
        if resolved.policy is not None:
            notify_admins_of_policy_change(
                self.team_id, str(resolved.policy.pk), resolved.policy.name, "created", self.request.user.pk
            )
        return Response(self.get_serializer(resolved).data)

    @extend_schema(request=None, responses={200: CITrustPolicyRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["ci_trust_policy_request:write"])
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._resolve(approve=True)

    @extend_schema(request=None, responses={200: CITrustPolicyRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["ci_trust_policy_request:write"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._resolve(approve=False)
