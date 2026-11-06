"""The public list of API scopes a person can grant, with what each one is for.

Built from the ScopeDoc declarations (posthog/scope_docs.py), so it lists exactly the scope objects
the web app's pickers offer. posthog.com reads it at build time for its scope reference, and
oauth.posthog.com proxies and caches it. The content only changes on deploy, so it is built once per
process and served with a long shared cache lifetime.
"""

from django.http import JsonResponse

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.scope_docs import SCOPE_GROUPS, get_scope_docs
from posthog.scopes import PRIVILEGED_SCOPES, RISKY_SCOPE_WARNINGS, APIScopeActions, get_oauth_scopes_supported

CACHE_MAX_AGE_SECONDS = 60 * 60


class ScopeActionSerializer(serializers.Serializer):
    action = serializers.CharField(help_text="The access level: `read` or `write`.")
    scope = serializers.CharField(help_text="The scope string a token carries, such as `feature_flag:read`.")
    oauth = serializers.BooleanField(
        help_text="Whether OAuth apps can request it on their own. Privileged scopes are granted only by PostHog."
    )
    warning = serializers.CharField(
        allow_null=True, help_text="What makes this scope risky to grant, when it is. Null otherwise."
    )


class ScopeRequirementSerializer(serializers.Serializer):
    scope = serializers.CharField(help_text="The other scope that writing this object also needs.")
    reason = serializers.CharField(help_text="Why the other scope is needed.")


class ScopeObjectSerializer(serializers.Serializer):
    object = serializers.CharField(help_text="The scope object, the part of a scope before the colon.")
    name = serializers.CharField(help_text="The name in sentence case, such as `Feature flag`.")
    plural = serializers.CharField(help_text="The lowercase plural, such as `feature flags`.")
    description = serializers.CharField(help_text="One sentence on what the scope object covers.")
    group = serializers.CharField(help_text="The product area the object belongs to. One of `groups`.")
    docs_url = serializers.URLField(allow_null=True, help_text="The posthog.com docs page for the feature, if any.")
    organization_wide = serializers.BooleanField(
        help_text="Whether the scope reaches past a single project, so keys limited to some projects cannot take it."
    )
    actions = ScopeActionSerializer(many=True, help_text="The access levels a person can grant for this object.")
    write_requires = ScopeRequirementSerializer(
        allow_null=True, help_text="A scope that write access to this object also needs, if any."
    )


class ScopeReferenceSerializer(serializers.Serializer):
    groups = serializers.ListField(
        child=serializers.CharField(), help_text="The product areas scope objects are grouped under, in display order."
    )
    objects = ScopeObjectSerializer(many=True, help_text="Every scope object a person can grant, sorted by object.")


def _action(scope_object: str, action: APIScopeActions, oauth_scopes: frozenset[str]) -> dict:
    scope = f"{scope_object}:{action}"
    return {
        "action": action,
        "scope": scope,
        "oauth": scope in oauth_scopes and scope not in PRIVILEGED_SCOPES,
        "warning": RISKY_SCOPE_WARNINGS.get(scope),
    }


_scope_reference: dict | None = None


def scope_reference() -> dict:
    global _scope_reference
    if _scope_reference is None:
        _scope_reference = _build_scope_reference()
    return _scope_reference


def _build_scope_reference() -> dict:
    oauth_scopes = frozenset(get_oauth_scopes_supported())
    return {
        "groups": list(SCOPE_GROUPS),
        "objects": [
            {
                "object": doc.object,
                "name": doc.name,
                "plural": doc.plural,
                "description": doc.description,
                "group": doc.group,
                "docs_url": doc.docs_url,
                "organization_wide": doc.organization_wide,
                "actions": [_action(doc.object, action, oauth_scopes) for action in doc.actions],
                "write_requires": (
                    {"scope": doc.write_requires.scope, "reason": doc.write_requires.reason}
                    if doc.write_requires
                    else None
                ),
            }
            for doc in get_scope_docs().values()
        ],
    }


class OAuthScopeReferenceView(APIView):
    permission_classes: list = []
    authentication_classes: list = []

    @extend_schema(
        responses={200: ScopeReferenceSerializer},
        tags=["oauth"],
        extensions={"x-product": "core"},
        summary="List grantable API scopes",
        description="Every API scope a person can grant to a personal API key or OAuth app, with what each one covers.",
    )
    def get(self, request: Request, *args, **kwargs) -> JsonResponse:
        response = JsonResponse(scope_reference())
        response["Access-Control-Allow-Origin"] = "*"
        response["Cache-Control"] = f"public, max-age={CACHE_MAX_AGE_SECONDS}"
        return response
