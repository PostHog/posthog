"""Workload trust policies: which workloads, such as CI jobs, may exchange an OIDC token for a project
token.

A policy hands out tokens that act as the organization owner, so it is a standing credential. Only an
organization admin or owner can read or write one, and writes need a browser session with recent
authentication, so no token can create or widen a policy. Any member can ask for a policy through a request.
"""

import json
import functools
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import APIException, NotFound
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnDict
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication, SessionAuthentication, WorkloadAccessTokenAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models import OrganizationMembership, Team, User
from posthog.models.oauth import OAuthApplication
from posthog.models.workload_trust_policy import (
    CONDITION_VALUE_MAX_LENGTH,
    CONDITIONS_MAX_BYTES,
    WorkloadTrustPolicy,
    WorkloadTrustPolicyRequest,
    workload_trust_policy_grantable_scopes,
    workload_trust_policy_request_url,
    workload_trust_policy_scopes_not_grantable,
)
from posthog.organization_caching import get_cached_organization_membership
from posthog.permissions import (
    OrganizationAdminReadPermissions,
    TimeSensitiveActionPermission,
    get_organization_from_view,
    get_required_organization_membership,
)
from posthog.rate_limit import (
    WorkloadSubjectLookupThrottle,
    WorkloadTrustPolicyRequestBurstThrottle,
    WorkloadTrustPolicyRequestSustainedThrottle,
)
from posthog.scopes import RISKY_SCOPE_WARNINGS
from posthog.tasks.email import WorkloadTrustPolicyChange, send_workload_trust_policy_changed
from posthog.workload_identity.providers import (
    SNIPPET_HOST,
    ConditionPreset,
    WorkloadProvider,
    WorkloadProviderKey,
    get_supported_workload_providers,
    get_workload_provider_by_issuer,
    get_workload_provider_by_key,
    normalize_issuer,
    workload_site_url,
)
from posthog.workload_identity.subjects import WorkloadSubjectLookupUnavailable, WorkloadSubjectNotFound

from products.access_control.backend.facade.subject_access_control import restricted_visible_membership_ids

# A policy matches claim values exactly, so a character that reads as a pattern is refused rather than
# taken literally: an admin who types `acme/*` expects every workload under `acme` to match, and none would.
WILDCARD_CHARACTERS = frozenset("*?[]")
DUPLICATE_POLICY_MESSAGE = "A policy for this workload with the same conditions already exists."
UNSUPPORTED_ISSUER_MESSAGE = "This issuer isn't a supported workload provider."
PROVIDER_MISMATCH_MESSAGE = "This issuer doesn't belong to the policy's workload provider."
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


def validate_supported_issuer(value: str) -> str:
    provider = get_workload_provider_by_issuer(value)
    if provider is None:
        raise serializers.ValidationError(UNSUPPORTED_ISSUER_MESSAGE)
    return normalize_issuer(provider.issuer)


def condition_claim_labels(provider: WorkloadProvider) -> dict[str, str]:
    return {claim.name: claim.label for claim in provider.condition_claims}


def supported_provider_for(issuer: str, provider_key: str | None = None) -> WorkloadProvider:
    """The registry entry for `issuer`. A stored `provider_key` must name that same entry, so a row never
    runs under the rules of a provider it wasn't written for."""
    provider = get_workload_provider_by_issuer(issuer)
    if provider is None:
        raise serializers.ValidationError({"issuer": UNSUPPORTED_ISSUER_MESSAGE})
    if provider_key is not None and provider.key != provider_key:
        raise serializers.ValidationError({"issuer": PROVIDER_MISMATCH_MESSAGE})
    return provider


def normalize_workload_conditions(conditions: Any, provider: WorkloadProvider) -> dict[str, str]:
    """The only form a policy or a request stores: the provider's condition claims, each with a non-empty
    exact string value, and the keys sorted. An empty value means the condition is not set, so it is
    dropped rather than stored as `""`, which would match no token and break the uniqueness check."""
    if not isinstance(conditions, dict):
        raise serializers.ValidationError({"conditions": "Send conditions as an object of claim names and values."})
    labels = condition_claim_labels(provider)
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


def validate_condition_companions(conditions: dict[str, str], provider: WorkloadProvider) -> None:
    labels = condition_claim_labels(provider)
    for rule in provider.condition_companions:
        alone = next((claim for claim in rule.claims if claim in conditions), None)
        if alone is not None and not any(name in conditions for name in rule.companions):
            needed = " or ".join(labels[name] for name in rule.companions)
            raise serializers.ValidationError({"conditions": f"{labels[alone]} needs {needed} too. {rule.reason}"})


def validate_workload_trust_conditions(attrs: dict[str, Any], *, instance: Any | None = None) -> dict[str, Any]:
    """Shared by policies and policy requests, so both enforce the same conditions. Sets `attrs["provider"]`
    from the issuer and normalizes `attrs["conditions"]` against that provider whenever the issuer or the
    conditions change."""
    if instance is not None and "issuer" not in attrs and "conditions" not in attrs:
        # Disabling or renaming a policy stays possible after its provider leaves the registry.
        return attrs
    if instance is None or "issuer" in attrs:
        provider = supported_provider_for(attrs["issuer"])
    else:
        provider = supported_provider_for(instance.issuer, instance.provider)
    attrs["provider"] = provider.key
    raw_conditions = attrs["conditions"] if "conditions" in attrs else getattr(instance, "conditions", {})
    attrs["conditions"] = normalize_workload_conditions(raw_conditions, provider)
    labels_by_claim = condition_claim_labels(provider)
    missing = [labels_by_claim[name] for name in provider.required_condition_claims if name not in attrs["conditions"]]
    if missing:
        raise serializers.ValidationError(
            {
                "conditions": f"{provider.name} policies must set {', '.join(missing)}, so no other account's workload matches."
            }
        )
    validate_condition_companions(attrs["conditions"], provider)
    account_claims = {*provider.required_condition_claims, *provider.account_condition_claims}
    run_claims = [claim for claim in provider.condition_claims if claim.name not in account_claims]
    if run_claims and not any(claim.name in attrs["conditions"] for claim in run_claims):
        labels = ", ".join(claim.label for claim in run_claims)
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


def workload_claim_labels(provider_key: str) -> dict[str, Any]:
    provider = get_workload_provider_by_key(provider_key)
    if provider is None:
        return {"subject": FALLBACK_SUBJECT_LABEL, "subject_name": FALLBACK_SUBJECT_NAME_LABEL, "conditions": {}}
    return {
        "subject": provider.subject_claim.label,
        "subject_name": provider.subject_name_claim.label,
        "conditions": condition_claim_labels(provider),
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
    issuer = serializers.CharField(
        max_length=255,
        help_text="The OIDC issuer of the workload provider, from the list of supported providers.",
    )
    provider = serializers.ChoiceField(
        choices=WorkloadProviderKey.choices,
        read_only=True,
        help_text="The key of the workload provider the issuer belongs to. PostHog sets it from the issuer.",
    )
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

    def validate_issuer(self, value: str) -> str:
        return validate_supported_issuer(value)

    def validate_subject_name(self, value: str) -> str:
        return _validate_exact_value(value, FALLBACK_SUBJECT_NAME_LABEL)

    def validate_subject(self, value: str) -> str:
        return _validate_exact_value(value, FALLBACK_SUBJECT_LABEL)

    @extend_schema_field(WorkloadClaimLabelsSerializer)
    def get_claim_labels(self, instance: WorkloadTrustPolicy | WorkloadTrustPolicyRequest) -> dict[str, Any]:
        return workload_claim_labels(instance.provider)


class WorkloadTrustPolicySerializer(WorkloadConditionsSerializerMixin, serializers.ModelSerializer):
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
    placeholder = serializers.CharField(allow_blank=True, help_text="An example value to show in an empty field.")


class ConditionCompanionsSerializer(serializers.Serializer):
    claims = serializers.ListField(
        child=serializers.CharField(), help_text="Condition claims a policy may set only with a companion."
    )
    companions = serializers.ListField(
        child=serializers.CharField(), help_text="Claims of which a policy must set at least one beside them."
    )
    reason = serializers.CharField(help_text="Why the claims need a companion, to show the person.")


class ConditionPresetSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Stable identifier of the preset within its provider.")
    label = serializers.CharField(help_text="What the UI calls the preset, like Pushes to a branch.")  # type: ignore[assignment]
    help_text = serializers.CharField(help_text="What runs the preset matches.")  # type: ignore[assignment]
    conditions = serializers.SerializerMethodField(
        help_text="Claim name to value. {value} stands for what the person types into the preset's field."
    )
    takes_value = serializers.BooleanField(help_text="Whether the preset has a field to type a value into.")
    placeholder = serializers.CharField(allow_blank=True, help_text="An example value for the preset's field.")
    default_value = serializers.CharField(allow_blank=True, help_text="The value the preset's field starts with.")

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_conditions(self, preset: ConditionPreset) -> dict[str, str]:
        return dict(preset.conditions)


class WorkloadProviderSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=WorkloadProviderKey.choices, help_text="Stable identifier of the provider.")
    name = serializers.CharField(help_text="Display name of the provider.")
    issuer = serializers.CharField(help_text="OIDC issuer a policy for this provider uses.")
    docs_url = serializers.CharField(help_text="Where to read how to set the provider up.")
    subject_claim = WorkloadClaimSerializer(help_text="The claim that carries the workload's immutable ID.")
    subject_name_claim = WorkloadClaimSerializer(help_text="The claim that carries the workload's readable name.")
    condition_claims = WorkloadClaimSerializer(
        many=True, help_text="The claims a policy can require an exact value for, in display order."
    )
    required_condition_claims = serializers.ListField(
        child=serializers.CharField(), help_text="Condition claims every policy for this provider must set."
    )
    account_condition_claims = serializers.ListField(
        child=serializers.CharField(),
        help_text="Condition claims that name the account and match every run, so they never limit which runs get a token.",
    )
    condition_presets = ConditionPresetSerializer(
        many=True, help_text="Common choices of conditions to offer before the raw claims, in display order."
    )
    condition_companions = ConditionCompanionsSerializer(
        many=True, help_text="Rules for condition claims that a policy may set only together with another claim."
    )
    required_presets = serializers.ListField(
        child=serializers.CharField(), help_text="Keys of the presets that set a condition claim every policy must set."
    )
    default_presets = serializers.ListField(
        child=serializers.CharField(), help_text="Keys of the presets a new policy starts with, in display order."
    )
    can_resolve_subject = serializers.SerializerMethodField(
        help_text="Whether PostHog can look up the subject from its name with resolve_subject."
    )
    subject_lookup_conditions = serializers.SerializerMethodField(
        help_text="Condition values a policy must have for resolve_subject to find its subject. Empty when any policy works."
    )
    setup_snippet = serializers.SerializerMethodField(
        help_text="The CI config a job needs to get a token for PostHog, empty when the provider has none."
    )

    def get_can_resolve_subject(self, provider: WorkloadProvider) -> bool:
        return provider.resolve_subject is not None

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_subject_lookup_conditions(self, provider: WorkloadProvider) -> dict[str, str]:
        return dict(provider.subject_lookup_conditions)

    def get_setup_snippet(self, provider: WorkloadProvider) -> str:
        # The job asks its provider for a token whose audience is this host.
        return provider.setup_snippet.replace(SNIPPET_HOST, workload_site_url())


class WorkloadJobSettingsSerializer(serializers.Serializer):
    host = serializers.CharField(help_text="The PostHog address a job sends its token to, which is its audience.")
    project_id = serializers.IntegerField(help_text="The project a job's token works in.")
    host_in_posthog_json = serializers.BooleanField(
        help_text="Whether hog reads the host from posthog.json. It does only for PostHog Cloud, so other hosts need HOG_HOST."
    )


class WorkloadProvidersResponseSerializer(serializers.Serializer):
    supported = WorkloadProviderSerializer(many=True, help_text="Providers a policy can trust.")
    job_settings = WorkloadJobSettingsSerializer(
        help_text="Where a job's host and project come from: posthog.json first, or HOG_HOST and HOG_PROJECT_ID."
    )
    grantable_scopes = serializers.ListField(
        child=serializers.CharField(), help_text="Every scope a policy's ceiling may hold."
    )
    risky_scopes = serializers.DictField(
        child=serializers.CharField(),
        help_text="What each grantable risky scope lets a token do, keyed by scope. Show it so people add the scope with care.",
    )


# hog reads a host from posthog.json only for these, because the file comes with the repository.
POSTHOG_JSON_HOSTS = ("https://us.posthog.com", "https://eu.posthog.com")


def workload_providers_data(project_id: int) -> ReturnDict:
    """The registry and job settings that the policy form and `hog ci setup` build their prompts from."""
    grantable = workload_trust_policy_grantable_scopes()
    host = workload_site_url()
    payload = {
        "supported": get_supported_workload_providers(),
        "job_settings": {"host": host, "project_id": project_id, "host_in_posthog_json": host in POSTHOG_JSON_HOSTS},
        "grantable_scopes": sorted(grantable),
        "risky_scopes": {scope: warning for scope, warning in RISKY_SCOPE_WARNINGS.items() if scope in grantable},
    }
    return WorkloadProvidersResponseSerializer(payload).data


def notify_admins_of_policy_change(
    team_id: int, policy_id: str, name: str, change: WorkloadTrustPolicyChange, actor_user_id: int | None
) -> None:
    # The change already happened, so a broker outage must not turn it into an error response.
    transaction.on_commit(
        lambda: send_workload_trust_policy_changed.delay(team_id, policy_id, name, change, actor_user_id), robust=True
    )


class DenyWorkloadAccessToken(BasePermission):
    """A workload token can never reach a policy or a request, not even to read, so it can't widen its own policy."""

    message = "Workload tokens can't use workload trust policy endpoints."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return not isinstance(request.successful_authenticator, WorkloadAccessTokenAuthentication)


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
        DenyWorkloadAccessToken,
        BrowserSessionWritePermission,
        NotImpersonatedWritePermission,
        TimeSensitiveActionPermission,
        OrganizationAdminReadPermissions,
    ]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return WorkloadTrustPolicy.objects.all().select_related("created_by").order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        policy = serializer.save(created_by=self.request.user)
        notify_admins_of_policy_change(self.team_id, str(policy.pk), policy.name, "created", self.request.user.pk)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        policy = serializer.save()
        notify_admins_of_policy_change(self.team_id, str(policy.pk), policy.name, "updated", self.request.user.pk)

    def perform_destroy(self, instance: WorkloadTrustPolicy) -> None:
        policy_id, name = str(instance.pk), instance.name
        instance.delete()
        notify_admins_of_policy_change(self.team_id, policy_id, name, "deleted", self.request.user.pk)

    @extend_schema(responses={200: WorkloadProvidersResponseSerializer})
    @action(methods=["GET"], detail=False, required_scopes=["workload_trust_policy:read"], pagination_class=None)
    def providers(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Policies live on the project's own team, which the exchange's `resource` names.
        return Response(workload_providers_data(self.team.project_id))


def requesting_application(request: Request) -> OAuthApplication | None:
    authenticator = request.successful_authenticator
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        return authenticator.access_token.application
    return None


class WorkloadTrustPolicyRequestSerializer(WorkloadConditionsSerializerMixin, serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, help_text="The name the policy gets once approved.")
    provider_name = serializers.SerializerMethodField(help_text="The display name of the workload provider, or null.")
    scopes = CIScopeListField(help_text="The scopes the policy's tokens would carry.")
    status = serializers.SerializerMethodField(help_text="Where the request stands. A request expires after 24 hours.")
    requested_via = serializers.SerializerMethodField(
        help_text="The name of the OAuth app the request came through, or null for other credentials."
    )
    requested_via_verified = serializers.SerializerMethodField(
        help_text="Whether PostHog verified the OAuth app the request came through, or null for other credentials."
    )
    approval_url = serializers.SerializerMethodField(help_text="The link to send to an admin to approve the request.")
    can_approve = serializers.SerializerMethodField(
        help_text="Whether the current user's role lets them approve the request, in the browser."
    )
    approvers = serializers.SerializerMethodField(
        help_text="Names of the organization admins and owners who can approve, when the current user cannot."
    )
    risky_scopes = serializers.SerializerMethodField(
        help_text="What each risky scope in the request lets a token do, keyed by scope. Show it before approving."
    )
    requested_by = UserBasicSerializer(read_only=True, allow_null=True)
    resolved_by = UserBasicSerializer(read_only=True, allow_null=True)
    policy_id = serializers.UUIDField(read_only=True, allow_null=True, help_text="The policy created on approval.")

    class Meta:
        model = WorkloadTrustPolicyRequest
        fields = [
            "id",
            "name",
            "issuer",
            "provider",
            "provider_name",
            "subject_name",
            "subject",
            "conditions",
            "claim_labels",
            "scopes",
            "risky_scopes",
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
            "claim_labels",
            "risky_scopes",
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
            "created_at": {"help_text": "When the request was made."},
            "expires_at": {"help_text": "When a pending request stops being approvable."},
            "resolved_at": {"help_text": "When an admin approved or rejected the request."},
        }

    def get_requested_via(self, policy_request: WorkloadTrustPolicyRequest) -> str | None:
        application = policy_request.requested_via_application
        return application.name if application else None

    def get_requested_via_verified(self, policy_request: WorkloadTrustPolicyRequest) -> bool | None:
        application = policy_request.requested_via_application
        return bool(application.is_verified or application.is_first_party) if application else None

    def get_provider_name(self, policy_request: WorkloadTrustPolicyRequest) -> str | None:
        provider = get_workload_provider_by_key(policy_request.provider)
        return provider.name if provider else None

    @extend_schema_field(serializers.ChoiceField(choices=WorkloadTrustPolicyRequest.Status.choices))
    def get_status(self, policy_request: WorkloadTrustPolicyRequest) -> str:
        return policy_request.effective_status

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_risky_scopes(self, policy_request: WorkloadTrustPolicyRequest) -> dict[str, str]:
        return {scope: RISKY_SCOPE_WARNINGS[scope] for scope in policy_request.scopes if scope in RISKY_SCOPE_WARNINGS}

    def get_approval_url(self, policy_request: WorkloadTrustPolicyRequest) -> str:
        return workload_trust_policy_request_url(policy_request.team_id, str(policy_request.pk))

    def get_can_approve(self, policy_request: WorkloadTrustPolicyRequest) -> bool:
        return bool(self.context["can_approve"])

    def get_approvers(self, policy_request: WorkloadTrustPolicyRequest) -> list[str]:
        return [] if self.context["can_approve"] else self.context["approvers"]()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return validate_workload_trust_conditions(attrs)


class WorkloadProviderUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The workload provider didn't answer. Try again in a minute."
    default_code = "workload_provider_unavailable"


class ResolveWorkloadSubjectQuerySerializer(serializers.Serializer):
    issuer = serializers.CharField(
        max_length=255, help_text="The OIDC issuer of the workload provider, from the list of supported providers."
    )
    subject_name = serializers.CharField(
        max_length=255,
        help_text="The name people know the workload by, from the provider's subject name claim, for example owner/repo.",
    )
    condition = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        default=list,
        help_text="The policy's conditions as claim=value, repeated. PostHog refuses a lookup they rule out, like a repository on a forge the lookup doesn't ask.",
    )

    def validate_issuer(self, value: str) -> str:
        return validate_supported_issuer(value)


class ResolvedWorkloadSubjectSerializer(serializers.Serializer):
    subject = serializers.CharField(help_text="The workload's immutable ID, for the policy's subject.")
    subject_name = serializers.CharField(
        help_text="The provider's exact spelling of the name, which the token carries, for the policy's subject name."
    )
    found_via = serializers.CharField(help_text="Where PostHog found the workload, to show the user.")


class WorkloadTrustPolicyRequestResolutionPermission(BasePermission):
    """Approving or rejecting a request needs an organization admin or owner in a browser session. Asking
    for a policy is open to every member, so the check applies to the resolving actions only."""

    message = (
        "Only an organization admin or owner can approve or reject a workload trust policy request, in the PostHog app."
    )

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) not in WorkloadTrustPolicyRequestViewSet.RESOLVING_ACTIONS:
            return True
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            return False
        membership = get_required_organization_membership(request, get_organization_from_view(view))
        return membership.level >= OrganizationMembership.Level.ADMIN


def resolve_workload_trust_policy_request(
    *, team_id: int, request_id: str, approve: bool, resolver: User, policy_serializer_context: dict[str, Any]
) -> WorkloadTrustPolicyRequest:
    """Approve or reject a pending request. Approving creates the policy from the request's own values,
    checked again against today's rules, in the same transaction that marks the request approved."""
    with transaction.atomic():
        policy_request = WorkloadTrustPolicyRequest.objects.select_for_update().get(pk=request_id, team_id=team_id)
        if policy_request.effective_status != WorkloadTrustPolicyRequest.Status.PENDING:
            raise serializers.ValidationError(f"This request is {policy_request.effective_status} and can't change.")
        if approve:
            # The policy serializer derives the provider from the issuer again, so this check keeps an
            # approval from turning a request for one provider into a policy for another.
            supported_provider_for(policy_request.issuer, policy_request.provider)
            policy_serializer = WorkloadTrustPolicySerializer(
                data={
                    field: getattr(policy_request, field)
                    for field in ("name", "issuer", "subject_name", "subject", "conditions", "scopes")
                },
                context=policy_serializer_context,
            )
            policy_serializer.is_valid(raise_exception=True)
            policy_request.policy = policy_serializer.save(created_by=resolver)
        policy_request.status = (
            WorkloadTrustPolicyRequest.Status.APPROVED if approve else WorkloadTrustPolicyRequest.Status.REJECTED
        )
        policy_request.resolved_by = resolver
        policy_request.resolved_at = timezone.now()
        policy_request.save()
    return policy_request


@extend_schema(extensions={"x-product": "core"})
class WorkloadTrustPolicyRequestViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    RESOLVING_ACTIONS = frozenset({"approve", "reject"})

    scope_object = "workload_trust_policy_request"
    queryset = WorkloadTrustPolicyRequest.objects.unscoped()
    serializer_class = WorkloadTrustPolicyRequestSerializer
    lookup_field = "id"
    permission_classes = [
        DenyWorkloadAccessToken,
        NotImpersonatedWritePermission,
        TimeSensitiveActionPermission,
        WorkloadTrustPolicyRequestResolutionPermission,
    ]
    # Asking for a policy grants nothing, so it never needs a fresh login. Approving and rejecting do.
    time_sensitive_exclude_actions = ["create"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return (
            WorkloadTrustPolicyRequest.objects.all()
            .select_related("requested_by", "resolved_by", "requested_via_application")
            .order_by("-created_at")
        )

    def get_throttles(self) -> list[Any]:
        if self.action == "create":
            return [WorkloadTrustPolicyRequestBurstThrottle(), WorkloadTrustPolicyRequestSustainedThrottle()]
        if self.action == "resolve_subject":
            return [WorkloadSubjectLookupThrottle()]
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
            # Name only the admins this reader could see in the members list, when the organization hides it.
            visible_membership_ids = restricted_visible_membership_ids(self.organization, cast(User, self.request.user))
            if visible_membership_ids is not None:
                memberships = memberships.filter(id__in=visible_membership_ids)
            return [membership.user.get_full_name() or membership.user.email for membership in memberships]

        context["approvers"] = approvers
        return context

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(
            team=self.team,
            requested_by=self.request.user,
            requested_via_application=requesting_application(self.request),
        )

    def _resolve(self, approve: bool) -> Response:
        policy_request = self.get_object()
        resolved = resolve_workload_trust_policy_request(
            team_id=policy_request.team_id,
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

    @validated_request(
        query_serializer=ResolveWorkloadSubjectQuerySerializer,
        responses={
            200: ResolvedWorkloadSubjectSerializer,
            404: OpenApiResponse(description="The provider has no such workload, or PostHog can't ask it."),
            503: OpenApiResponse(description="The provider didn't answer."),
        },
    )
    @action(methods=["GET"], detail=False, required_scopes=["workload_trust_policy_request:read"])
    def resolve_subject(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        """Find a workload's immutable ID from the name people know it by, so nobody has to look the ID up
        to ask for or write a policy."""
        provider = supported_provider_for(request.validated_query_data["issuer"])
        if provider.resolve_subject is None:
            raise NotFound(f"PostHog can't look up {provider.subject_claim.label} for {provider.name}.")
        # Generated clients join a list into one comma-separated value, so each value may hold several entries.
        entries = [part for value in request.validated_query_data["condition"] for part in value.split(",")]
        given = dict(entry.split("=", 1) for entry in entries if "=" in entry)
        unmet = [(claim, value) for claim, value in provider.subject_lookup_conditions if given.get(claim) != value]
        if unmet:
            claim, value = unmet[0]
            label = condition_claim_labels(provider).get(claim, claim)
            raise NotFound(f"PostHog can look up {provider.subject_claim.label} only when {label} is {value}.")
        try:
            resolved = provider.resolve_subject(self.team_id, request.validated_query_data["subject_name"])
        except WorkloadSubjectNotFound as e:
            raise NotFound(str(e))
        except WorkloadSubjectLookupUnavailable as e:
            raise WorkloadProviderUnavailable(str(e))
        return Response(ResolvedWorkloadSubjectSerializer(resolved).data)

    @extend_schema(responses={200: WorkloadProvidersResponseSerializer})
    @action(
        methods=["GET"], detail=False, required_scopes=["workload_trust_policy_request:read"], pagination_class=None
    )
    def providers(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The supported providers and the settings a job needs, for any member who asks for a policy."""
        return Response(workload_providers_data(self.team.project_id))

    @extend_schema(request=None, responses={200: WorkloadTrustPolicyRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["workload_trust_policy_request:write"])
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._resolve(approve=True)

    @extend_schema(request=None, responses={200: WorkloadTrustPolicyRequestSerializer})
    @action(methods=["POST"], detail=True, required_scopes=["workload_trust_policy_request:write"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._resolve(approve=False)
