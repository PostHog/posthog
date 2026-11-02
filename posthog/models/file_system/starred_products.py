from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.db.models import QuerySet

from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut, lock_user_shortcuts
from posthog.models.user import User
from posthog.products import Products
from posthog.schema_enums import ProductItemCategory, ProductKey

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.product_intent.product_intent import ProductIntent
    from posthog.models.team import Team

# The products every user starts with in a project. Paths must match `path` values in frontend/src/products.json.
DEFAULT_PRODUCT_PATHS = [
    "Product analytics",
    "Dashboards",
    "Web analytics",
    "Error tracking",
    "Session replay",
]


def _project_shortcuts(user: User, team: "Team") -> QuerySet[FileSystemShortcut]:
    # The sidebar lists the shortcuts of every environment in the project, so checks span them all.
    # nosemgrep: environment-model-scoped-by-project -- the shortcut API lists a user's own stars project-wide
    return FileSystemShortcut.objects.filter(surface_q(DEFAULT_SURFACE), team__project_id=team.project_id, user=user)


def _product_stars(user: User, team: "Team") -> QuerySet[FileSystemShortcut]:
    # Product stars have no ref. Starred files and folders point at their item through one.
    return _project_shortcuts(user, team).filter(ref__isnull=True).exclude(type="folder")


def has_starred_product(user: User, team: "Team", product_paths: list[str]) -> bool:
    """Whether the user starred any of these products anywhere in the team's project."""
    return _product_stars(user, team).filter(path__in=product_paths).exists()


def star_products(user: User, team: "Team", product_paths: list[str]) -> int:
    """Star products on the user's sidebar for a team, after their existing stars. Returns how many were added.

    Unknown paths and products the user already starred are skipped, so a repeated call adds nothing.
    """
    products_by_path = {product.path: product for product in Products.products()}
    with transaction.atomic():
        # Concurrent writes for the same user would otherwise both miss the star and add it twice.
        lock_user_shortcuts(team.pk, user.pk)
        user_shortcuts = _project_shortcuts(user, team)
        starred_paths = set(_product_stars(user, team).values_list("path", flat=True))
        next_order = max(user_shortcuts.values_list("order", flat=True), default=0) + 1

        to_create: list[FileSystemShortcut] = []
        for path in product_paths:
            product = products_by_path.get(path)
            if product is None or path in starred_paths:
                continue
            starred_paths.add(path)
            # No href: product URLs live only in the frontend, which fills it in from the product list.
            to_create.append(
                FileSystemShortcut(
                    team=team,
                    user=user,
                    path=path,
                    type=product.iconType or product.type or "",
                    surface=DEFAULT_SURFACE,
                    order=next_order + len(to_create),
                )
            )
        FileSystemShortcut.objects.bulk_create(to_create)
    return len(to_create)


def star_default_products(user: User, team: "Team") -> None:
    """Star the default products for a user who just got access to a project.

    A user who already has product stars in the project made their own choice, so nothing is added.
    """
    if _product_stars(user, team).exists():
        return
    star_products(user, team, DEFAULT_PRODUCT_PATHS)


def star_default_products_for_accessible_teams(user: User, organization: "Organization") -> None:
    """Star the default products in every project of the organization the user has access to."""
    from products.access_control.backend.facade.user_access_control import (  # noqa: PLC0415 - avoids a circular import
        UserAccessControl,
    )

    uac = UserAccessControl(user=user, organization_id=str(organization.id))
    accessible_teams = uac.filter_queryset_by_access_level(organization.teams.all(), include_all_if_admin=True)

    for team in accessible_teams:
        star_default_products(user, team)


def star_released_products(user: User, team: "Team") -> None:
    """Star every released product. Unreleased products stay opt-in, so they are left out."""
    star_products(
        user,
        team,
        [product.path for product in Products.products() if product.category != ProductItemCategory.UNRELEASED],
    )


def star_products_from_intent(product_intent: "ProductIntent", user: User) -> None:
    """Star the products behind a new product intent, unless the user turned off sidebar suggestions.

    Call this only when the intent is first created. Intents are registered again every time the
    product is used, so starring on every call would bring back products the user unstarred.
    """
    if user.allow_sidebar_suggestions is False:
        return
    products = Products.get_products_by_intent(cast(ProductKey, product_intent.product_type))
    star_products(user, product_intent.team, [product.path for product in products])
