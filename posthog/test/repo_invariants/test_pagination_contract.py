from collections.abc import Iterator
from typing import Any

from django.urls import URLPattern, URLResolver, get_resolver

from rest_framework.generics import GenericAPIView
from rest_framework.pagination import BasePagination, CursorPagination
from rest_framework.viewsets import ViewSetMixin

from posthog.api.pagination import BoundedLimitOffsetPagination, BoundedPageNumberPagination, StableCursorPagination
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
    "products.managed_migrations.backend.api.support_batch_imports.BatchImportSupportViewSet",
    "products.reminders.backend.api.reminder.ReminderViewSet",
    "products.workflows.backend.presentation.views.hog_flow.HogFlowViewSet",
    "products.workflows.backend.presentation.views.hog_flow_template.PublicHogFlowTemplateViewSet",
}


def _url_patterns(patterns: list[URLPattern | URLResolver]) -> Iterator[URLPattern]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns)
        else:
            yield pattern


def _class_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _pagination_class(callback: Any, view: type[GenericAPIView]) -> type[BasePagination] | None:
    return getattr(callback, "initkwargs", {}).get("pagination_class", view.pagination_class)


def _base_to_use(pagination_class: type[BasePagination]) -> str | None:
    if issubclass(pagination_class, CursorPagination):
        if issubclass(pagination_class, StableCursorPagination):
            return None
        return "StableCursorPagination, so rows that share a sort value cannot move a page boundary"
    if issubclass(pagination_class, (BoundedLimitOffsetPagination, BoundedPageNumberPagination)):
        return None
    return "BoundedLimitOffsetPagination, so one request cannot ask for a whole table"


def test_paginators_extend_the_shared_bases() -> None:
    problems: set[str] = set()
    for pattern in _url_patterns(get_resolver().url_patterns):
        view = getattr(pattern.callback, "cls", None) or getattr(pattern.callback, "view_class", None)
        if view is None or not issubclass(view, GenericAPIView):
            continue
        pagination_class = _pagination_class(pattern.callback, view)
        if pagination_class is None:
            continue
        base = _base_to_use(pagination_class)
        if base is not None:
            problems.add(f"{_class_name(pagination_class)} (used by {_class_name(view)}): subclass {base}")

    assert not problems, "Paginators must extend a base in posthog/api/pagination.py:\n  " + "\n  ".join(
        sorted(problems)
    )


def test_new_list_viewsets_review_their_pagination_contract() -> None:
    list_viewsets: set[str] = set()
    for pattern in _url_patterns(get_resolver().url_patterns):
        viewset = getattr(pattern.callback, "cls", None)
        actions = getattr(pattern.callback, "actions", None) or {}
        if viewset is None or not issubclass(viewset, ViewSetMixin) or "list" not in actions.values():
            continue
        if not issubclass(viewset, GenericAPIView):
            continue
        pagination_class = _pagination_class(pattern.callback, viewset)
        if pagination_class is None or issubclass(pagination_class, CursorPagination):
            continue
        if (
            issubclass(viewset, TeamAndOrgViewSetMixin)
            and viewset.paginate_queryset is TeamAndOrgViewSetMixin.paginate_queryset
        ):
            continue
        list_viewsets.add(_class_name(viewset))

    unreviewed = sorted(list_viewsets - LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION)
    assert not unreviewed, (
        "New standard list viewsets need a stable ordering and a page-boundary test, or a reviewed exception:\n  "
        + "\n  ".join(unreviewed)
    )

    stale = sorted(LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION - list_viewsets)
    assert not stale, "Remove standard list viewsets that no longer bypass shared pagination:\n  " + "\n  ".join(stale)
