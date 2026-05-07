---
name: move-admins-to-product
description: Move a Django admin class out of the central `posthog/admin/admins/` registry and into the owning product's `backend/admin.py`. Use when adding admin coverage for a product, when refactoring an existing entry in `posthog/admin/admins/` for cleanup, when reviewing PRs that introduce a new admin class, or whenever editing files under `posthog/admin/admins/` or `products/*/backend/admin.py`. Covers the `ADMIN_REGISTRATIONS` tuple contract, the `LazyAdminRegistry`-driven reason `@admin.register` is forbidden, and the pitfalls around `ProductTeamModel`, capped inlines, and tach interfaces.
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

2. **Define the registration tuple.** At the bottom of `products/<name>/backend/admin.py`, expose:

   ```python
   ADMIN_REGISTRATIONS: tuple[tuple[type, type[admin.ModelAdmin]], ...] = (
       (Model, ModelAdmin),
       ...
   )
   ```

   No allowlist edit, no `@admin.register` decorator.
   `posthog/admin/__init__.py::_register_dynamic_product_admins()` walks every `products.*` app config, imports the `admin` submodule if present, and registers anything it finds in `ADMIN_REGISTRATIONS`.
   String-based `importlib.import_module(...)` keeps tach happy for isolated products — `posthog/` never names the internal admin module.

   **Don't use `@admin.register(...)`** — it's also forbidden by the `no-admin-register-decorator` semgrep rule.
   PostHog's `LazyAdminRegistry` swap in `posthog/apps.py::_setup_lazy_admin` runs _after_ Django's autodiscover, so any `@admin.register`-time registrations get wiped before `register_all_admin()` runs and the admin is silently missing in production.

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

- **`LazyAdminRegistry` wipes autodiscover-time registrations.** The swap in `posthog/apps.py::_setup_lazy_admin` runs _after_ `AdminConfig.ready()` autodiscover, so any `@admin.register(...)` decorator on a product admin module registers on the real `admin.site._registry` only to have that registry replaced moments later. The lazy registry is non-empty by the time admin is hit, but only the `register_all_admin()` calls it triggers populated it — autodiscover work is gone. Always go through `ADMIN_REGISTRATIONS`. The `no-admin-register-decorator` semgrep rule fails CI if a decorator slips in.

- **`@admin.register` + `patch.object(admin, "site", ...)` mismatch (related).** Even ignoring the wipe, the decorator imports `default_site` from `django.contrib.admin.sites`, which `patch.object(admin, "site", AdminSite())` does NOT patch (it swaps the package re-export). `posthog/admin/test_admin.py::test_register_admin_models_succeeds` patches admin.site that way; `@admin.register` registers on the unpatched real site, breaking the test guarantee. `register_all_admin()` calling `admin.site.register(...)` itself goes through whatever `admin.site` is in scope, which is the right thing in both production and tests.

- **`ProductTeamModel`-backed models and `TeamScopeError`.** `ProductTeamModel.Meta.default_manager_name = "all_teams"` already routes Django's framework managers (`_default_manager`, `_base_manager`) at the unscoped sibling — admin queryset, `ForeignKeyRawIdWidget` label rendering, related-object access, generic relations, `prefetch_related`, and DRF default querysets all read through `all_teams` automatically. Admin works without per-class plumbing. `Model.objects.filter(...)` (the explicit attribute) stays bound to `TeamScopedManager` and stays fail-closed. If you see `TeamScopeError` in admin, the product probably doesn't extend `ProductTeamModel`; check `posthog/models/scoping/README.md`.

- **Slicing in an inline's `get_queryset`.** Crashes the change page with "Cannot filter a query once a slice has been taken." See the `BaseInlineFormSet` pattern above.

- **Django admin link names.** `admin:<app_label>_<model_name>_change`. The app_label comes from the product's `AppConfig.label` (often the short product name like `visual_review`, not the dotted path), not the model module. Use `reverse(...)` — don't hard-code paths.

## Reference

The visual_review admin (PR #57879, `products/visual_review/backend/admin.py`) is the canonical example: isolated product, `ProductTeamModel`-backed, all six models covered, capped inline, perf hygiene, no `@admin.register`. The `posthog/admin/__init__.py` change in that PR shows the dynamic-discovery wiring for isolated products.

## Design notes — possible future cleanup

The `LazyAdminRegistry` swap + the `no-admin-register-decorator` ban are compensating for the fact that `'django.contrib.admin'` is in `INSTALLED_APPS`, which means Django's `AdminConfig.ready()` runs `autodiscover_modules('admin')` at startup.
The proper Django-native fix would be to swap `'django.contrib.admin'` for `'django.contrib.admin.apps.SimpleAdminConfig'` in `INSTALLED_APPS`.
`SimpleAdminConfig` exists precisely to disable the autodiscover pass, so registrations happen only through whatever the project explicitly invokes (in PostHog's case, `register_all_admin()`).
Combined with a custom `AdminSite` subclass that exposes `_registry` as a `cached_property` of the loaded dict (Django's documented [overriding-the-default-admin-site](https://docs.djangoproject.com/en/4.2/ref/contrib/admin/#overriding-the-default-admin-site) escape hatch), the `LazyAdminRegistry(dict)` swap and the autodiscover-vs-swap race both go away.

That refactor is out of scope for the per-product admin migration.
But it would let `@admin.register(...)` work everywhere (since there'd be no registry-replacement to wipe its work), making both the ban and `ADMIN_REGISTRATIONS` redundant.
Worth scoping as a follow-up once the bulk of admins have moved into their products.
