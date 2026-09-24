from collections.abc import Iterator

from django.urls import URLPattern, URLResolver, get_resolver

from rest_framework.generics import GenericAPIView
from rest_framework.pagination import BasePagination, CursorPagination

from posthog.api.pagination import StableCursorPagination, StableOrderingPaginationMixin
from posthog.dataclasses import frozen

# Shrink-only. These viewsets do not inherit TeamAndOrgViewSetMixin, so their pages get no primary key
# tiebreaker. Delete an entry when its viewset inherits StableOrderingPaginationMixin.
ROOT_VIEWSETS_WITHOUT_STABLE_ORDERING = {
    "posthog.api.async_migration.AsyncMigrationsViewset",
    "posthog.api.authentication.DevLoginViewSet",
    "posthog.api.dead_letter_queue.DeadLetterQueueViewSet",
    "posthog.api.instance_settings.InstanceSettingsViewset",
    "posthog.api.personal_api_key.PersonalAPIKeyViewSet",
    "posthog.api.user.UserViewSet",
    "posthog.api.user_integration.UserIntegrationViewSet",
    "products.cdp.backend.api.hog_function_template.PublicHogFunctionTemplateViewSet",
    "products.managed_migrations.backend.api.support_batch_imports.BatchImportSupportViewSet",
    "products.reminders.backend.api.reminder.ReminderViewSet",
    "products.workflows.backend.api.hog_flow_template.PublicHogFlowTemplateViewSet",
}


@frozen
class PaginatedViewSet:
    name: str
    viewset: type[GenericAPIView]
    pagination_class: type[BasePagination]


def _url_patterns(patterns: list) -> Iterator[URLPattern]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            yield pattern


def _paginated_list_viewsets() -> list[PaginatedViewSet]:
    viewsets: dict[str, PaginatedViewSet] = {}
    for pattern in _url_patterns(get_resolver().url_patterns):
        viewset = getattr(pattern.callback, "cls", None)
        actions = getattr(pattern.callback, "actions", None) or {}
        if viewset is None or not issubclass(viewset, GenericAPIView) or "list" not in actions.values():
            continue
        if viewset.pagination_class is None:
            continue
        name = f"{viewset.__module__}.{viewset.__qualname__}"
        viewsets[name] = PaginatedViewSet(name=name, viewset=viewset, pagination_class=viewset.pagination_class)
    return list(viewsets.values())


def _has_unstable_cursor_paginator_attribute(pagination_class: type[BasePagination]) -> bool:
    return any(
        isinstance(attribute, CursorPagination) and not isinstance(attribute, StableCursorPagination)
        for attribute in vars(pagination_class()).values()
    )


def test_cursor_paginators_add_a_primary_key_tiebreaker() -> None:
    unstable = sorted(
        f"{paginated.name} ({paginated.pagination_class.__qualname__})"
        for paginated in _paginated_list_viewsets()
        if (
            issubclass(paginated.pagination_class, CursorPagination)
            and not issubclass(paginated.pagination_class, StableCursorPagination)
        )
        or _has_unstable_cursor_paginator_attribute(paginated.pagination_class)
    )

    assert not unstable, (
        "These cursor paginators order only by the fields they declare, so rows that tie on the cursor field "
        "can repeat or go missing across pages. Subclass posthog.api.pagination.StableCursorPagination:\n  "
        + "\n  ".join(unstable)
    )


def test_root_viewsets_page_with_a_stable_ordering() -> None:
    root_viewsets = {
        paginated.name
        for paginated in _paginated_list_viewsets()
        if not issubclass(paginated.pagination_class, CursorPagination)
        and not issubclass(paginated.viewset, StableOrderingPaginationMixin)
    }

    new_viewsets = sorted(root_viewsets - ROOT_VIEWSETS_WITHOUT_STABLE_ORDERING)
    assert not new_viewsets, (
        "These viewsets page without a primary key tiebreaker, so rows that tie on the ordering field "
        "can repeat or go missing across pages. Inherit posthog.api.pagination.StableOrderingPaginationMixin:\n  "
        + "\n  ".join(new_viewsets)
    )

    stale_entries = sorted(ROOT_VIEWSETS_WITHOUT_STABLE_ORDERING - root_viewsets)
    assert not stale_entries, "Remove these entries from ROOT_VIEWSETS_WITHOUT_STABLE_ORDERING:\n  " + "\n  ".join(
        stale_entries
    )
