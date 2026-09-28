from typing import TYPE_CHECKING, Any

import posthoganalytics

from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.products import Products

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

# pinned: feature flag key, must match FEATURE_FLAGS.SIMPLE_SIDEPANEL in frontend/src/lib/constants.tsx
SIMPLE_SIDEPANEL_FLAG = "simple-sidepanel"


def starred_products_setup_completed(user: "User") -> bool:
    configuration = user.ui_configuration
    sidebar = configuration.get("sidebar") if isinstance(configuration, dict) else None
    return isinstance(sidebar, dict) and bool(sidebar.get("starred_products_setup_completed"))


def _simple_sidebar_enabled(user: "User", team: "Team") -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            SIMPLE_SIDEPANEL_FLAG,
            str(user.distinct_id),
            person_properties={"email": user.email},
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def _mark_setup_completed(user: "User") -> None:
    configuration: dict[str, Any] = user.ui_configuration if isinstance(user.ui_configuration, dict) else {}
    sidebar = configuration.get("sidebar")
    user.ui_configuration = {
        "version": 1,
        **configuration,
        "sidebar": {**(sidebar if isinstance(sidebar, dict) else {}), "starred_products_setup_completed": True},
    }
    user.save(update_fields=["ui_configuration"])


def star_custom_products(user: "User", team: "Team", product_paths: list[str], *, had_custom_products: bool) -> None:
    """Star products that were just added to a user's custom products, for simple sidebar users.

    The simple sidebar shows starred products instead of custom products, so every write that adds
    custom products calls this to keep the two in step. `had_custom_products` says whether the user
    had any custom products, in any project, before the write:

    - A user with none is brand new, so their products are starred and the setup is marked done.
    - A user who finished the setup gets the new products starred too.
    - A user with custom products who has not done the setup yet is left alone. The setup card
      offers their whole list, so starring one suggestion must not complete it for them.
    """
    if not product_paths:
        return
    completed = starred_products_setup_completed(user)
    if not completed and had_custom_products:
        return
    if not _simple_sidebar_enabled(user, team):
        return

    products_by_path = {product.path: product for product in Products.products()}
    user_shortcuts = FileSystemShortcut.objects.filter(surface_q(DEFAULT_SURFACE), team=team, user=user)
    starred_paths = set(user_shortcuts.filter(ref__isnull=True).exclude(type="folder").values_list("path", flat=True))
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

    if not completed:
        _mark_setup_completed(user)
