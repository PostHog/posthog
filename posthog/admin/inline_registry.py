"""Cross-app admin inline registration.

Lets a product surface a Django admin inline on a *core* admin page (e.g. the
Organization change page) without core importing the product. A Django inline must be
listed in its parent ModelAdmin, and core admins live in posthog/admin/ — so a product
that owns an inline would otherwise force a core -> product import, breaking the product's
isolation boundary.

Instead the product registers its inline against the parent *model* at admin-autodiscover
time, and the parent admin pulls registered inlines in get_inlines(). Keying by model class
(not by importing the parent ModelAdmin) keeps the dependency one-way (product -> posthog)
and avoids the auth.admin circular-import gotcha.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.admin.options import InlineModelAdmin
    from django.db.models import Model

_extra_inlines: dict[type[Model], list[type[InlineModelAdmin]]] = {}


def register_admin_inline(parent_model: type[Model], inline_cls: type[InlineModelAdmin]) -> None:
    """Attach an admin inline to `parent_model`'s admin page from another app.

    Call at admin-module import time (autodiscover) — e.g. in a product's backend/admin.py.
    The parent admin must opt in by adding extra_inlines_for() to its get_inlines(). Idempotent.
    """
    inlines = _extra_inlines.setdefault(parent_model, [])
    if inline_cls not in inlines:
        inlines.append(inline_cls)


def extra_inlines_for(parent_model: type[Model]) -> list[type[InlineModelAdmin]]:
    """Inlines other apps registered for `parent_model`, in registration order."""
    return list(_extra_inlines.get(parent_model, []))
