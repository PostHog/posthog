"""Workload trust policies: which workloads, such as CI jobs, may exchange an OIDC token for a project
token.

A policy hands out tokens that act as the organization owner, so it is a standing credential. Only an
organization admin or owner can read or write one, and writes need a browser session with recent
authentication, so no token can create or widen a policy.
"""

import json
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema, extend_schema_field
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
    CONDITION_VALUE_MAX_LENGTH,
    CONDITIONS_MAX_BYTES,
    WorkloadTrustPolicy,
    workload_trust_policy_grantable_scopes,
    workload_trust_policy_scopes_not_grantable,
)
from posthog.permissions import OrganizationAdminReadPermissions, TimeSensitiveActionPermission
from posthog.scopes import RISKY_SCOPE_WARNINGS
from posthog.tasks.email import WorkloadTrustPolicyChange, send_workload_trust_policy_changed
from posthog.workload_identity.providers import (
    WorkloadProvider,
    get_supported_workload_providers,
    get_workload_provider_by_issuer,
    normalize_issuer,
)

# A policy matches claim values exactly, so a character that reads as a pattern is refused rather than
# taken literally: an admin who types `acme/*` expects every workload under `acme` to match, and none would.
WILDCARD_CHARACTERS = frozenset("*?[]")
DUPLICATE_POLICY_MESSAGE = "A policy for this workload with the same conditions already exists."
FALLBACK_SUBJECT_LABEL = "Subject"
FALLBACK_SUBJECT_NAME_LABEL = "Name"


def _validate_exact_value(value: str, field_label: str) -> str:
    stripped = value.strip()
    if stripped != value:
        raise serializers.ValidationError(f"{field_label} must not start or end with whitespace.")
    if "\x00" in value:
        raise serializers.ValidationError(f"{field_label} must not contain a null character.")
    if any(character in WILDCARD_CHARACTERS for character in value):
        raise serializers.ValidationError(f"{field_label} must be an exact value. Wildcards are not supported.")
    return value


def normalize_workload_conditions(conditions: Any, provider: WorkloadProvider) -> dict[str, str]:
    """The only form a policy or a request stores: the provider's condition claims, each with a non-empty
    exact string value, and the keys sorted. An empty value means the condition is not set, so it is
    dropped rather than stored as `""`, which would match no token and break the uniqueness check."""
    if not isinstance(conditions, dict):
        raise serializers.ValidationError({"conditions": "Send conditions as an object of claim names and values."})
    labels = {claim.name: claim.label for claim in provider.condition_claims}
    normalized: dict[str, str] = {}
    for claim, value in conditions.items():
        if claim not in labels:
            allowed = ", ".join(labels) or "none"
            raise serializers.ValidationError(
                {
                    "conditions": f"{provider.name} doesn't support a condition on {str(claim)[:100]!r}. Allowed: {allowed}."
                }
            )
        label = labels[claim]
        if not isinstance(value, str):
            raise serializers.ValidationError({"conditions": f"{label} must be text."})
        if not value:
            continue
        if len(value) > CONDITION_VALUE_MAX_LENGTH:
            raise serializers.ValidationError(
                {"conditions": f"{label} can be at most {CONDITION_VALUE_MAX_LENGTH} characters long."}
            )
        try:
            normalized[claim] = _validate_exact_value(value, label)
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"conditions": e.detail})
    canonical = dict(sorted(normalized.items()))
    if len(json.dumps(canonical, ensure_ascii=False).encode()) > CONDITIONS_MAX_BYTES:
        raise serializers.ValidationError({"conditions": "The conditions are too long. Shorten the values."})
    return canonical


def validate_workload_trust_conditions(attrs: dict[str, Any], *, instance: Any | None = None) -> dict[str, Any]:
    """Shared by policies and policy requests, so both enforce the same conditions. Normalizes
    `attrs["conditions"]` against the issuer's provider whenever the issuer or the conditions change."""
    if instance is not None and "issuer" not in attrs and "conditions" not in attrs:
        # Disabling or renaming a policy stays possible after its provider leaves the registry.
        return attrs
    issuer = attrs["issuer"] if "issuer" in attrs else getattr(instance, "issuer", "")
    provider = get_workload_provider_by_issuer(issuer)
    if provider is None:
        raise serializers.ValidationError({"issuer": "This issuer isn't a supported workload provider."})
    raw_conditions = attrs["conditions"] if "conditions" in attrs else getattr(instance, "conditions", {})
    attrs["conditions"] = normalize_workload_conditions(raw_conditions, provider)
    if provider.condition_claims and not attrs["conditions"]:
        labels = ", ".join(claim.label for claim in provider.condition_claims)
        raise serializers.ValidationError(
            {
                "conditions": f"Set at least one condition ({labels}) so the policy doesn't match every token for this workload."
            }
        )
    return attrs


@extend_schema_field(serializers.DictField(child=serializers.CharField()))
class WorkloadConditionsField(serializers.Field):
    """Claim name to required value. The serializer's `validate` normalizes it once the provider is known."""

    def to_internal_value(self, data: Any) -> Any:
        return data

    def to_representation(self, value: Any) -> dict[str, Any]:
        return dict(sorted(value.items())) if isinstance(value, dict) else {}


class WorkloadClaimLabelsSerializer(serializers.Serializer):
    subject = serializers.CharField(help_text="What the provider calls the subject, for example Repository ID.")
    subject_name = serializers.CharField(help_text="What the provider calls the subject name, for example Repository.")
    conditions = serializers.DictField(
        child=serializers.CharField(),
        help_text="The label of each condition claim the provider allows, keyed by claim name.",
    )


def workload_claim_labels(issuer: str) -> dict[str, Any]:
    provider = get_workload_provider_by_issuer(issuer)
    if provider is None:
        return {"subject": FALLBACK_SUBJECT_LABEL, "subject_name": FALLBACK_SUBJECT_NAME_LABEL, "conditions": {}}
    return {
        "subject": provider.subject_claim.label,
        "subject_name": provider.subject_name_claim.label,
        "conditions": {claim.name: claim.label for claim in provider.condition_claims},
    }


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
            raise serializers.ValidationError("This issuer isn't a supported workload provider.")
        return normalize_issuer(provider.issuer)

    def validate_subject_name(self, value: str) -> str:
        return _validate_exact_value(value, FALLBACK_SUBJECT_NAME_LABEL)

    def validate_subject(self, value: str) -> str:
        return _validate_exact_value(value, FALLBACK_SUBJECT_LABEL)

    @extend_schema_field(WorkloadClaimLabelsSerializer)
    def get_claim_labels(self, instance: Any) -> dict[str, Any]:
        return workload_claim_labels(instance.issuer)


class WorkloadTrustPolicySerializer(WorkloadConditionsSerializerMixin, serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, help_text="A name that says what the policy is for.")
    issuer = serializers.CharField(
        max_length=255,
        help_text="The OIDC issuer of the workload provider, from the list of supported providers.",
    )
    provider = serializers.SerializerMethodField(help_text="The key of the workload provider the issuer belongs to.")
    subject_name = serializers.CharField(
        max_length=255,
        help_text=(
            "The workload's human-readable name, from the provider's subject name claim, for example a repository's "
            "full name. Matched exactly."
        ),
    )
    subject = serializers.CharField(
        max_length=255,
        help_text=(
            "The workload's immutable ID, from the provider's subject claim, for example a repository ID. Matched "
            "exactly together with the name, so a deleted and re-created workload with the same name does not match."
        ),
    )
    conditions = WorkloadConditionsField(
        required=False,
        help_text=(
            "Claims the token must carry, as claim name to exact value, for example a branch or an environment. "
            "Only the provider's condition claims are allowed. An empty value removes the condition."
        ),
    )
    claim_labels = serializers.SerializerMethodField(
        help_text="How the provider names the subject, the subject name and each condition claim, for display."
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
            "subject_name",
            "subject",
            "conditions",
            "claim_labels",
            "scopes",
            "enabled",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "provider", "claim_labels", "created_by", "created_at", "updated_at"]

    def get_provider(self, policy: WorkloadTrustPolicy) -> str | None:
        provider = get_workload_provider_by_issuer(policy.issuer)
        return provider.key if provider else None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = validate_workload_trust_conditions(attrs, instance=self.instance)
        team = cast(Team, self.context["get_team"]())
        identity = {
            field: attrs.get(field, getattr(self.instance, field, None))
            for field in ("issuer", "subject", "conditions")
        }
        clash = WorkloadTrustPolicy.objects.filter(**identity)
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


class WorkloadClaimSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The claim's name in the provider's OIDC token.")
    label = serializers.CharField(help_text="What to call the claim in the UI.")  # type: ignore[assignment]
    help_text = serializers.CharField(  # type: ignore[assignment]
        allow_blank=True, help_text="A hint that says where to find the claim's value."
    )


class WorkloadProviderSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable identifier of the provider.")
    name = serializers.CharField(help_text="Display name of the provider.")
    issuer = serializers.CharField(help_text="OIDC issuer a policy for this provider uses.")
    docs_url = serializers.CharField(help_text="Where to read how to set the provider up.")
    subject_claim = WorkloadClaimSerializer(help_text="The claim that carries the workload's immutable ID.")
    subject_name_claim = WorkloadClaimSerializer(help_text="The claim that carries the workload's readable name.")
    condition_claims = WorkloadClaimSerializer(
        many=True, help_text="The claims a policy can require an exact value for, in display order."
    )


class WorkloadProvidersResponseSerializer(serializers.Serializer):
    supported = WorkloadProviderSerializer(many=True, help_text="Providers a policy can trust.")
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
            "supported": get_supported_workload_providers(),
            "grantable_scopes": sorted(grantable),
            "risky_scopes": {scope: warning for scope, warning in RISKY_SCOPE_WARNINGS.items() if scope in grantable},
        }
        return Response(WorkloadProvidersResponseSerializer(payload).data)
