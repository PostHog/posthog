# PostHog Admin console

The staff back office at `/admin/console/`.
It replaces custom Django admin views and templates for staff workflows.
The Django admin stays for plain CRUD on models.

## Invariants

- **Every console route sits under `/admin/` and is wrapped in `admin.site.admin_view`.** `AdminOAuth2Middleware` adds the Google step-up for every `/admin/` path, and `admin_view` adds the staff check and CSRF protection. The console has no auth of its own, so a route outside that prefix or without that wrapper is unprotected.
- **Staff operations never go through DRF, MCP, or API keys.** Keys and MCP tokens skip the admin step-up. An operation is a Python callable that a console view runs.
- **A panel returns data, not markup.** Subclass `Panel` and return `Fact` and `Operation` objects. Do not write templates, `format_html`, or `mark_safe` for a panel. The shell renders every panel the same way, so a new panel cannot drift from the design.
- **Only the shell writes templates** (`posthog/templates/admin_console/`). They use quill's `quill-*` classes and Tailwind utilities, with the markup quill's React components emit, including their `data-*` attributes.
- **A destructive operation sets `danger=True` and asks for a reason** (an `OperationField`). The reason goes to the team or the audit trail through the handler.

## Add a panel

1. In `products/<product>/backend/console.py`, subclass `Panel` and decorate it with `@console.register_panel`. Import only your product's `facade/` and `posthog.admin.console`. `products/workflows/backend/console.py` is the reference.
2. Set `owner = Owner(name=..., crest=...)`. The crest is a mini crest slug from `@posthog/brand`, for example `workflows`.
3. For each action, return an `Operation`. Its `handler` is a service function, or `AdminViewBridge(Model, SomeAdmin.view_method)` while the logic still lives in a `ModelAdmin`. A bridged view must take a POST and answer with a redirect. Later, replace the bridge with a service function; the panel stays as it is.
4. Run `pnpm --filter=@posthog/frontend build:admin-console` when you add an owner crest or change a template. `posthog/admin/test_admin_console.py` fails when a template class or an owner crest is missing from the build output.

## Read when needed

- `frontend/src/design.md`: quill component choice and states. Read it before you change a template.
- `packages/quill/packages/primitives/AGENTS.md`: the markup and attributes of each quill primitive. Read it before you add a quill class to a template.
