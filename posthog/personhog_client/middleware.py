from django.http import HttpRequest, HttpResponse
from django.urls import resolve
from django.urls.exceptions import Resolver404

from posthog.personhog_client.gate import pin_personhog_decision, unpin_personhog_decision
from posthog.personhog_client.interceptor import set_caller_tag


class PersonHogGateMiddleware:
    """Pin the personhog gate decision for the lifetime of an HTTP request.

    This ensures that all personhog-routed calls within a single request
    consistently use the same backend (either all gRPC or all ORM),
    avoiding mixed-source reads during partial rollout.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        pin_personhog_decision()
        try:
            return self.get_response(request)
        finally:
            unpin_personhog_decision()


# DRF view_name prefix → caller tag.
# view_name is "{basename}-{action}", e.g. "persons-list", "project_cohorts-detail".
# Checked with startswith so "persons-list" matches prefix "persons".
_VIEW_NAME_TO_CALLER_TAG: dict[str, str] = {
    "persons": "api/persons",
    "environment_persons": "api/persons",
    "project_feature_flags": "api/feature-flags",
    "feature_flag": "api/feature-flags",
    "organization_feature_flags": "api/feature-flags",
    "project_cohorts": "api/cohorts",
    "cohort": "api/cohorts",
    "environment_groups": "api/groups",
    "project_groups_types": "api/group-types",
    "project_groups_metrics": "api/group-types",
    "project_insights": "api/insights",
    "environment_insights": "api/insights",
    "project_dashboards": "api/dashboards",
    "environment_exports": "api/exports",
    "project_experiments": "api/experiments",
    "environment_events": "api/events",
    "event": "api/events",
    "project_session_recordings": "api/session-recordings",
    "environment_session_recordings": "api/session-recordings",
    "project_query": "api/query",
    "environment_query": "api/query",
}


def _resolve_caller_tag(request: HttpRequest) -> str:
    try:
        route = resolve(request.path)
    except Resolver404:
        return "web/unresolved"

    view_name = route.view_name or ""

    for prefix, tag in _VIEW_NAME_TO_CALLER_TAG.items():
        if view_name.startswith(prefix):
            return tag

    if "api/" in request.path:
        return "api/other"

    return "web/other"


class PersonHogCallerTagMiddleware:
    """Derive an x-caller-tag from the resolved Django URL name.

    Sets the caller_tag ContextVar so that downstream personhog gRPC calls
    carry the tag via CallerTagInterceptor.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tag = _resolve_caller_tag(request)
        token = set_caller_tag(tag)
        try:
            return self.get_response(request)
        finally:
            from posthog.personhog_client.interceptor import _caller_tag

            _caller_tag.reset(token)
