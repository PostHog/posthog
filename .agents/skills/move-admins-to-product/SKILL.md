---
name: move-admins-to-product
description: Move a Django admin class out of the central `posthog/admin/admins/` registry and into the owning product's `backend/admin.py`. Use when adding admin coverage for a product, when refactoring an existing entry in `posthog/admin/admins/` for cleanup, when reviewing PRs that introduce a new admin class, or whenever editing files under `posthog/admin/admins/` or `products/*/backend/admin.py`. Also covers the choice between `@admin.register` (non-isolated products) and the explicit `ADMIN_REGISTRATIONS` tuple (isolated products), plus the pitfalls around `ProductTeamModel`, capped inlines, and tach interfaces.
---

# Moving admins into the product

Per-product admin is the default. New admin classes should land in `products/<name>/backend/admin.py`, not in `posthog/admin/admins/`. This skill covers both greenfield product admins and migrating an existing entry out of the central registry.

Unlike moving models into a product, moving an admin doesn't require the product to be isolated and doesn't touch the schema — the mechanical steps are mostly imports + registration shape. Lazy-loading is preserved: Django's admin autodiscover still imports `backend/admin.py` at startup, and the actual `admin.site.register(...)` calls still fire only when `register_all_admin()` runs (gated by `LazyAdminRegistry` on the first admin request).

## When to migrate

- Adding admin coverage for a product that currently has none.
- Touching an admin class in `posthog/admin/admins/<x>_admin.py` whose model lives in `products/<name>/`. Move it instead of editing in place.
- Reviewing a PR that adds a new entry to `posthog/admin/admins/`. Push back — it should live in the product.

Don't migrate core posthog admins (Organization, Team, User, Dashboard, etc.). Those legitimately belong in `posthog/admin/admins/`.

## Workflow

1. **Find the surface to move.** For product `<name>`:

   ```sh
   rg -n "<ModelName>" posthog/admin/admins posthog/admin/__init__.py
   ```

   Expect three call sites: a file under `posthog/admin/admins/`, an entry in `posthog/admin/admins/__init__.py` (`from .x_admin import …` and the `__all__` list), and an explicit `admin.site.register(Model, …Admin)` line in `posthog/admin/__init__.py::register_all_admin()`.

2. **Decide the registration shape.** Check `products/<name>/package.json`:

   - **Not isolated** (no `backend:contract-check` script): use `@admin.register(Model)` decorators in `products/<name>/backend/admin.py`. Django's stock admin autodiscover at `AdminConfig.ready()` walks `INSTALLED_APPS` and imports each app's `admin` submodule, which fires the decorators. No edits needed in `posthog/admin/__init__.py`.
   - **Isolated** (has `backend:contract-check`): tach forbids `posthog/` from importing `products.<name>.backend.admin` directly. Don't use `@admin.register` — use an explicit `ADMIN_REGISTRATIONS = ((Model, AdminClass), …)` tuple at the bottom of `backend/admin.py`, and add the product's app name (`products.<name>.backend`) to `_PRODUCTS_WITH_DYNAMIC_ADMIN` in `posthog/admin/__init__.py`. The string-based `importlib.import_module(f"{app}.admin")` keeps the tach interface honest while letting `register_all_admin()` wire up the registrations against the current `admin.site`.

3. **Move the file.** `posthog/admin/admins/<x>_admin.py` → `products/<name>/backend/admin.py`. If the product already has an `admin.py`, append the class. Adjust imports — model imports go from absolute (`posthog.…`) to relative (`from .models import …`), or absolute to the product's path if the product chose absolute style.

4. **Strip the central wiring.**

   - Remove the file from `posthog/admin/admins/`.
   - Remove the `from .<x>_admin import …Admin` line and the matching entry in `__all__` from `posthog/admin/admins/__init__.py`.
   - Remove the `from posthog.admin.admins import …Admin` and the explicit `admin.site.register(Model, …Admin)` lines from `posthog/admin/__init__.py::register_all_admin()`.

5. **Verify.**

   - `tach check --dependencies --interfaces` — no boundary regression.
   - `posthog/admin/test_admin.py::TestAdmin::test_register_admin_models_succeeds` — exercises `register_all_admin()` end-to-end. The canonical guardrail.
   - `ruff check` and `ruff format --check` on the changed files.
   - Click through the moved admin in `./bin/start`: list view, change page, FK widget popups, any inlines.

## Patterns to lift while you're in there

This isn't required for the migration to be correct, but the visual_review admin landed all of these and they're easy to copy.

- **Performance hygiene** for high-cardinality tables: `show_full_result_count = False`, `paginator = NoCountPaginator` (from `posthog.admin.paginators.no_count_paginator`), `raw_id_fields` for FKs whose targets can be large, `list_select_related` for FKs displayed in the list view.
- **Capped inline pattern** for child tables that grow without bound. Slice in a `BaseInlineFormSet` subclass's `get_queryset`, **not** in `Inline.get_queryset` — Django's inline formset filters by parent FK after `Inline.get_queryset` returns, and slicing breaks subsequent `.filter()` calls.

  ```python
  class _LimitedFooFormSet(BaseInlineFormSet):
      def get_queryset(self):
          return super().get_queryset().order_by("-created_at")[:25]

  class FooInline(admin.TabularInline):
      formset = _LimitedFooFormSet
  ```

- **Read-only fieldsets** for rows that are written by ingestion / pipelines, not hand-edited.

## Pitfalls

These are the things that bit the visual_review admin PR. Worth checking explicitly:

- **`@admin.register` + `patch.object(admin, "site", ...)` mismatch.** The decorator imports `default_site` from `django.contrib.admin.sites`, which `patch.object(admin, "site", AdminSite())` does **not** touch — `patch.object` swaps the package re-export, the decorator reads from the source module. `posthog/admin/test_admin.py::test_register_admin_models_succeeds` patches admin.site this way; using `@admin.register` plus an `importlib.reload` to re-fire decorators in `register_all_admin()` re-registers on the unpatched real site and crashes with `AlreadyRegistered`. For isolated products, use the explicit `ADMIN_REGISTRATIONS` tuple shape — `register_all_admin()` calls `admin.site.register(...)` itself and goes through whatever `admin.site` is in scope.

- **`ProductTeamModel`-backed models and `TeamScopeError`.** `ProductTeamModel.Meta.default_manager_name = "all_teams"` already routes Django's framework managers (`_default_manager`, `_base_manager`) at the unscoped sibling — admin queryset, `ForeignKeyRawIdWidget` label rendering, related-object access, generic relations, `prefetch_related`, and DRF default querysets all read through `all_teams` automatically. Admin works without per-class plumbing. `Model.objects.filter(...)` (the explicit attribute) stays bound to `TeamScopedManager` and stays fail-closed. If you see `TeamScopeError` in admin, the product probably doesn't extend `ProductTeamModel`; check `posthog/models/scoping/README.md`.

- **Slicing in an inline's `get_queryset`.** Crashes the change page with "Cannot filter a query once a slice has been taken." See the `BaseInlineFormSet` pattern above.

- **Django admin link names.** `admin:<app_label>_<model_name>_change`. The app_label comes from the product's `AppConfig.label` (often the short product name like `visual_review`, not the dotted path), not the model module. Use `reverse(...)` — don't hard-code paths.

## Reference

The visual_review admin (PR #57879, `products/visual_review/backend/admin.py`) is the canonical example: isolated product, `ProductTeamModel`-backed, all six models covered, capped inline, perf hygiene, no `@admin.register`. The `posthog/admin/__init__.py` change in that PR shows the dynamic-discovery wiring for isolated products.
