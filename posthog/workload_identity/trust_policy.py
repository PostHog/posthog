"""Workload trust policies: which workloads, such as a repository's CI jobs, may exchange an OIDC token
for a project token.

A policy hands out tokens that act as the organization owner, so it is a standing credential. Only an
organization admin or owner can read or write one, and writes need a browser session with recent
authentication, so no token can create or widen a policy.
"""

from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import SessionAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.workload_trust_policy import (
    WorkloadTrustPolicy,
    workload_trust_policy_grantable_scopes,
    workload_trust_policy_scopes_not_grantable,
)
from posthog.permissions import OrganizationAdminReadPermissions, TimeSensitiveActionPermission
from posthog.scopes import RISKY_SCOPE_WARNINGS
from posthog.tasks.email import WorkloadTrustPolicyChange, send_workload_trust_policy_changed
from posthog.workload_identity.providers import (
    get_supported_workload_providers,
    get_unsupported_workload_providers,
    get_workload_provider_by_issuer,
    normalize_issuer,
)

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


def validate_workload_trust_conditions(attrs: dict[str, Any], *, partial_instance: Any | None = None) -> dict[str, Any]:
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
        not_grantable = workload_trust_policy_scopes_not_grantable(scopes)
        if not_grantable:
            raise serializers.ValidationError(
                f"These scopes can't be granted to workloads: {', '.join(not_grantable)}. "
                "A workload token can't outlive itself or change its own policy, and can't use privileged or hidden scopes."
            )
        return sorted(set(scopes))


class WorkloadConditionsSerializerMixin(serializers.Serializer):
    def validate_issuer(self, value: str) -> str:
        provider = get_workload_provider_by_issuer(value)
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


class WorkloadTrustPolicySerializer(WorkloadConditionsSerializerMixin, serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, help_text="A name that says what the policy is for.")
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
        model = WorkloadTrustPolicy
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

    def get_provider(self, policy: WorkloadTrustPolicy) -> str | None:
        provider = get_workload_provider_by_issuer(policy.issuer)
        return provider.key if provider else None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = validate_workload_trust_conditions(attrs, partial_instance=self.instance)
        team = cast(Team, self.context["get_team"]())
        conditions = {
            field: attrs.get(field, getattr(self.instance, field, ""))
            for field in ("issuer", "repository_id", "ref", "environment")
        }
        clash = WorkloadTrustPolicy.objects.filter(**conditions)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(DUPLICATE_POLICY_MESSAGE)
        attrs["team"] = team
        return attrs

    def create(self, validated_data: dict[str, Any]) -> WorkloadTrustPolicy:
        try:
            return super().create(validated_data)
        except IntegrityError:
            # Two writes with the same conditions can both pass the check in `validate`.
            raise serializers.ValidationError(DUPLICATE_POLICY_MESSAGE)

    def update(self, instance: WorkloadTrustPolicy, validated_data: dict[str, Any]) -> WorkloadTrustPolicy:
        try:
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError(DUPLICATE_POLICY_MESSAGE)


class WorkloadProviderClaimsSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="Claim that carries the repository's full name.")
    repository_id = serializers.CharField(help_text="Claim that carries the repository's immutable ID.")
    ref = serializers.CharField(allow_null=True, help_text="Claim that carries the git ref, or null.")
    environment = serializers.CharField(allow_null=True, help_text="Claim that carries the environment, or null.")


class WorkloadProviderSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable identifier of the provider.")
    name = serializers.CharField(help_text="Display name of the provider.")
    issuer = serializers.CharField(help_text="OIDC issuer a policy for this provider uses.")
    docs_url = serializers.CharField(help_text="Where to read how to set the provider up.")
    claims = WorkloadProviderClaimsSerializer(help_text="Which token claims a policy matches on.")


class UnsupportedWorkloadProviderSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable identifier of the provider.")
    name = serializers.CharField(help_text="Display name of the provider.")
    reason = serializers.CharField(help_text="Why the provider can't be used.")


class WorkloadProvidersResponseSerializer(serializers.Serializer):
    supported = WorkloadProviderSerializer(many=True, help_text="Providers a policy can trust.")
    unsupported = UnsupportedWorkloadProviderSerializer(many=True, help_text="Known providers that can't be trusted.")
    grantable_scopes = serializers.ListField(
        child=serializers.CharField(), help_text="Every scope a policy's ceiling may hold."
    )
    risky_scopes = serializers.DictField(
        child=serializers.CharField(),
        help_text="What each grantable risky scope lets a token do, keyed by scope. Show it so people add the scope with care.",
    )


class NotImpersonatedWritePermission(BasePermission):
    """A policy is a standing credential that acts as the owner, so staff impersonating a member can read
    policies but not change them, or ask for them."""

    message = (
        "Workload trust policies act as the organization owner, so they can't be changed while impersonating a user."
    )

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.method in SAFE_METHODS or not is_impersonated(request)


class BrowserSessionWritePermission(BasePermission):
    """Writes need a browser session. Every token type gets a 403, because a token can only ask for a
    policy, which an admin then approves in the browser."""

    message = "Workload trust policies can only be changed in the PostHog app, by an organization admin."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return isinstance(request.successful_authenticator, SessionAuthentication)


@extend_schema(extensions={"x-product": "core"})
class WorkloadTrustPolicyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "workload_trust_policy"
    queryset = WorkloadTrustPolicy.objects.unscoped()
    serializer_class = WorkloadTrustPolicySerializer
    lookup_field = "id"
    permission_classes = [
        BrowserSessionWritePermission,
        NotImpersonatedWritePermission,
        TimeSensitiveActionPermission,
        OrganizationAdminReadPermissions,
    ]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return WorkloadTrustPolicy.objects.all().select_related("created_by").order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        policy = serializer.save(created_by=self.request.user)
        self._notify_admins(policy, "created")

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        policy = serializer.save()
        self._notify_admins(policy, "updated")

    def perform_destroy(self, instance: WorkloadTrustPolicy) -> None:
        policy_id, name = str(instance.pk), instance.name
        instance.delete()
        self._notify_admins_of(policy_id, name, "deleted")

    def _notify_admins(self, policy: WorkloadTrustPolicy, change: WorkloadTrustPolicyChange) -> None:
        self._notify_admins_of(str(policy.pk), policy.name, change)

    def _notify_admins_of(self, policy_id: str, name: str, change: WorkloadTrustPolicyChange) -> None:
        team_id = self.team_id
        actor_user_id = cast(User, self.request.user).pk
        # The change already happened, so a broker outage must not turn it into an error response.
        transaction.on_commit(
            lambda: send_workload_trust_policy_changed.delay(team_id, policy_id, name, change, actor_user_id),
            robust=True,
        )

    @extend_schema(responses={200: WorkloadProvidersResponseSerializer})
    @action(methods=["GET"], detail=False, required_scopes=["workload_trust_policy:read"], pagination_class=None)
    def providers(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        grantable = workload_trust_policy_grantable_scopes()
        payload = {
            "supported": [
                {
                    "key": provider.key,
                    "name": provider.name,
                    "issuer": provider.issuer,
                    "docs_url": provider.docs_url,
                    "claims": {
                        "repository": provider.claims.repository,
                        "repository_id": provider.pinned_claim,
                        "ref": provider.claims.ref,
                        "environment": provider.claims.environment,
                    },
                }
                for provider in get_supported_workload_providers()
            ],
            "unsupported": [
                {"key": provider.key, "name": provider.name, "reason": provider.reason}
                for provider in get_unsupported_workload_providers()
            ],
            "grantable_scopes": sorted(grantable),
            "risky_scopes": {scope: warning for scope, warning in RISKY_SCOPE_WARNINGS.items() if scope in grantable},
        }
        return Response(WorkloadProvidersResponseSerializer(payload).data)
