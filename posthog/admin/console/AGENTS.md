# PostHog Admin console

The staff back office at `/admin/console/`.
It replaces custom Django admin views and templates for staff workflows.
The `no-new-custom-admin-views` semgrep rule blocks new ones, and the program ends when its findings reach zero.
The Django admin stays for plain CRUD on models.

## Invariants

- **Every console route sits under `/admin/` and is wrapped in `admin.site.admin_view`.** `AdminOAuth2Middleware` adds the Google step-up for every `/admin/` path, and `admin_view` adds the staff check and CSRF protection. The console has no auth of its own, so a route outside that prefix or without that wrapper is unprotected.
- **Staff operations never go through DRF, MCP, or API keys.** Keys and MCP tokens skip the admin step-up. An operation is a Python callable that a console view runs.
- **A panel returns data, not markup.** Subclass `Panel` and return `Fact` and `Operation` objects. Do not write templates, `format_html`, or `mark_safe` for a panel. The shell renders every panel the same way, so a new panel cannot drift from the design.
- **Only the shell writes templates** (`posthog/templates/admin_console/`). They use quill's `quill-*` classes and Tailwind utilities, with the markup quill's React components emit, including their `data-*` attributes.
- **A destructive operation sets `danger=True` and has a form with a `reason` field.** `Operation` refuses it otherwise, and the console writes the reason to the audit log.

## Add a panel

1. In `products/<product>/backend/console.py`, subclass `Panel` and decorate it with `@console.register_panel`. Import only your product's `facade/` and `posthog.admin.console`. `products/workflows/backend/console.py` is the reference.
2. Set `owner = Owner(name=..., crest=...)`. The crest is a mini crest slug from `@posthog/brand`, for example `workflows`.
3. For each action, return an `Operation`. Put its inputs in a Django `forms.Form` (`form_class`); the console renders and validates it. Its `handler(request, obj, form)` returns `None` when done. The handler is a service function, or `AdminViewBridge(Model, SomeAdmin.view_method)` while the logic still lives in a `ModelAdmin`. A bridged view must take a POST and answer with a redirect. Later, replace the bridge with a service function; the panel stays as it is.
4. Run `pnpm --filter=@posthog/frontend build:admin-console` when you add an owner crest or change a template. `posthog/admin/test_admin_console.py` fails when a template class or an owner crest is missing from the build output.

## Add a tool

A tool is a page that is not about one record, for example a report across all teams.

1. In `products/<product>/backend/console.py`, subclass `ConsoleTool` and decorate it with `@console.register_tool`. Set `key`, `title`, `owner` and `group`; the group is the navigation heading. `posthog/admin/console/events_retention_tool.py` is the reference.
2. `page(request)` returns a `Page` of blocks (`Notice`, `Table` with `Row` and `GroupRow`, `Paging`). The console renders the blocks, so a tool needs no template. When a tool needs a block that does not exist, add it to `tools.py` and `tool.html` in the shell, not a template in the product.
3. When a tool replaces a Django admin page, keep the old URL name as a redirect to the tool, so existing links keep working.

## Read when needed

- `frontend/src/design.md`: quill component choice and states. Read it before you change a template.
- `packages/quill/packages/primitives/AGENTS.md`: the markup and attributes of each quill primitive. Read it before you add a quill class to a template.
