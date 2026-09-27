from collections.abc import Iterator

from django.urls import URLPattern, URLResolver, get_resolver

from rest_framework.generics import GenericAPIView
from rest_framework.pagination import CursorPagination

from posthog.api.routing import TeamAndOrgViewSetMixin

LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION = {
    "posthog.api.async_migration.AsyncMigrationsViewset",
    "posthog.api.authentication.DevLoginViewSet",
    "posthog.api.dead_letter_queue.DeadLetterQueueViewSet",
    "posthog.api.instance_settings.InstanceSettingsViewset",
    "posthog.api.personal_api_key.PersonalAPIKeyViewSet",
    "posthog.api.user.UserViewSet",
    "posthog.api.user_integration.UserIntegrationViewSet",
    "products.cdp.backend.api.hog_function_template.PublicHogFunctionTemplateViewSet",
    "products.conversations.backend.api.tickets.TicketViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountViewSet",
    "products.dashboards.backend.api.dashboard.LegacyInsightViewSet",
    "products.managed_migrations.backend.api.support_batch_imports.BatchImportSupportViewSet",
    "products.product_analytics.backend.presentation.insight_ee.EnterpriseInsightsViewSet",
    "products.reminders.backend.api.reminder.ReminderViewSet",
    "products.workflows.backend.api.hog_flow_template.PublicHogFlowTemplateViewSet",
}


def _url_patterns(patterns: list[URLPattern | URLResolver]) -> Iterator[URLPattern]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns)
        else:
            yield pattern


def test_new_list_viewsets_review_their_pagination_contract() -> None:
    list_viewsets: set[str] = set()
    for pattern in _url_patterns(get_resolver().url_patterns):
        viewset = getattr(pattern.callback, "cls", None)
        actions = getattr(pattern.callback, "actions", None) or {}
        if viewset is None or not issubclass(viewset, GenericAPIView) or "list" not in actions.values():
            continue
        pagination_class = getattr(pattern.callback, "initkwargs", {}).get("pagination_class", viewset.pagination_class)
        if pagination_class is None or issubclass(pagination_class, CursorPagination):
            continue
        if (
            issubclass(viewset, TeamAndOrgViewSetMixin)
            and viewset.paginate_queryset is TeamAndOrgViewSetMixin.paginate_queryset
        ):
            continue
        list_viewsets.add(f"{viewset.__module__}.{viewset.__qualname__}")

    unreviewed = sorted(list_viewsets - LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION)
    assert not unreviewed, (
        "New list viewsets need a stable ordering and a page-boundary test, or a reviewed exception:\n  "
        + "\n  ".join(unreviewed)
    )

    stale = sorted(LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION - list_viewsets)
    assert not stale, "Remove viewsets that no longer bypass shared pagination:\n  " + "\n  ".join(stale)
