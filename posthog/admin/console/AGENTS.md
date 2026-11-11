# PostHog Admin console

The staff back office at `/admin/console/`.
It replaces custom Django admin views and templates for staff workflows.
The `no-new-custom-admin-views` semgrep rule blocks new ones, and the program ends when its findings reach zero.
The Django admin stays for plain CRUD on models.
Before you add or change a panel, operation or tool, invoke `/extending-the-admin-console`. It holds the judgment calls: where a change goes, copy, how to classify an operation, and the checks before done.

## Invariants

- **Every console route sits under `/admin/` and is wrapped in `admin.site.admin_view`.** `AdminOAuth2Middleware` adds the Google step-up for every `/admin/` path, and `admin_view` adds the staff check and CSRF protection. The console has no auth of its own, so a route outside that prefix or without that wrapper is unprotected.
- **Staff operations never go through DRF, MCP, or API keys.** Keys and MCP tokens skip the admin step-up. An operation is a Python callable that a console view runs.
- **A panel returns data, not markup.** Subclass `Panel` and return `Fact` and `Operation` objects. Do not write templates, `format_html`, or `mark_safe` for a panel. The shell renders every panel the same way, so a new panel cannot drift from the design.
- **Only the shell writes templates** (`posthog/templates/admin_console/`). They use quill's `quill-*` classes and Tailwind utilities, with the markup quill's React components emit, including their `data-*` attributes.
- **A destructive operation sets `danger=True`, has a form with a `reason` field, and sets `undo_hint`.** `Operation` refuses it otherwise. The console writes the reason to the audit log and shows the undo hint on the confirm page.
- **An operation that only some staff may run sets `gate`.** Use `Gate.owner()`, which lets in the members of the `staff_group` on the panel or tool's `Owner`, so a group name appears only in its `Owner`. `Gate.owner()` under an `Owner` without `staff_group` raises `ValueError` when the console renders or runs the operation, so only a test that reaches a state that offers the operation catches it. Use `Gate.group(name)` only for a group of another team, or a `Gate` with a reviewed rule. Never gate on a Django model permission: `User.is_superuser` mirrors `is_staff`, so every staff member passes. The console shows a gated operation disabled with who may run it, and refuses the request with 403.
- **The contract checks itself.** The registry refuses a key that is not a slug, a blank title and a tool group outside `TOOL_GROUPS`. `Fact` refuses markup, and `Page` refuses unknown blocks and table rows of the wrong width. When a check fires, fix the contribution. Do not loosen the check in the same change.

## Add a panel

1. In `products/<product>/backend/console.py`, subclass `Panel` and decorate it with `@console.register_panel`. Set `record` to a key from `RECORD_TYPES` in `records.py` (`team`, `organization` or `deletion-request`). Import only your product's `facade/`, `posthog.admin.console`, and, for a bridge, the `ModelAdmin` that still holds the view. `products/workflows/backend/console.py` is the reference.
2. Set `owner = Owner(name=..., crest=...)`. The crest is a mini crest slug from `@posthog/brand`, for example `workflows`. Define each `Owner` once and import it. Add `staff_group` when the team gates operations with `Gate.owner()`. `migrate` and `ensure_migration_defaults` create that group on dev, test and hobby databases. In production, create the group in Django admin and add the staff who run those operations. A local `migrate` and `manage.py check --database default` warn when the group is missing.
3. For each action, return an `Operation`. Put its inputs in a Django `forms.Form` (`form_class`); the console renders and validates it. Its `handler(request, obj, form)` returns `None` when done. The handler is a service function, or `AdminViewBridge(Model, SomeAdmin.view_method)` while the logic still lives in a `ModelAdmin`. A bridged view must take a POST and answer with a redirect. Later, replace the bridge with a service function; the panel stays as it is.
4. Run `pnpm --filter=@posthog/frontend build:admin-console` when you add an owner crest or change a template. `posthog/admin/test_admin_console.py` fails when a template class, a linked asset or an owner crest is missing from the build output.

## Add a tool

A tool is a page that is not about one record, for example a report across all teams.

1. In `products/<product>/backend/console.py`, subclass `ConsoleTool` and decorate it with `@console.register_tool`. Set `key`, `title`, `owner` and `group`; the group is the navigation heading. `posthog/admin/console/events_retention_tool.py` is the reference.
2. `page(request)` returns a `Page` of blocks (`Notice`, `Table` with `Row` and `GroupRow`, `Paging`, `Output`, `Live`). It only reads; the console serves it for GET and HEAD only. The console renders the blocks, so a tool needs no template. When a tool needs a block that does not exist, add it to `tools.py` and `tool.html` in the shell, not a template in the product.
3. For an action that is not about one record, return a `ToolOperation` from `operations(request)`. It works like a record `Operation` without the record: `handler(request, form)`. Its handler returns `None` (back to the tool with its messages), or a `Page` that the console shows once as the result. The console redirects to the result, so a reload never runs the operation again. `products/cohorts/backend/console.py` is the reference.
4. A credential that staff must copy now, such as a password the control plane returns only once, goes in a `Secret` block on a result `Page`, from a tool or a record operation. The console keeps the result for one read, so the value never reaches the audit log, a confirm token, a URL or a message. A tool page or a preview refuses it. `products/managed_warehouse/backend/console.py` is the reference.
5. An operation that changes many records at once sets `preview`. The console shows the preview `Page` and a confirm button, and the confirm runs exactly the previewed input from a signed token. The handler still re-checks the current state, because records can change between preview and confirm. The token is readable, so a form with a preview holds no secrets. `posthog/admin/console/organization_tools.py` is the reference.
6. A block that should follow running work, such as the runs of a started job, is a `Live` block. Return it from `live(request, key)` and embed the same call in `page`. Keep `refresh_seconds` set while something runs and None once nothing does, so the page stops asking. `posthog/admin/console/health_checks_tool.py` is the reference.
7. When a tool replaces a Django admin page, keep the old path and point it at `MovedToConsole.page_redirect`, so bookmarks keep working. Keep its URL name too when the name lives in the root URLconf, such as `ee/urls.py`. A name in the `admin:` namespace only exists inside a `ModelAdmin.get_urls`, which the freeze rule flags, so drop it once `rg` finds no caller that reverses it.

## Move a Django admin action

Replace the old button with `MovedToConsole.action(record, obj, panel_key, label)` from `moved.py`. It links to the panel on the console record page, so staff who look in the usual place find the new one. When a whole page moves, route its old URL to `MovedToConsole.page_redirect(title, url)`, which tells staff the page moved.
Old URLs never break, because staff keep bookmarks to them, query parameters included. When a record action's view is deleted, its old path goes into the `MOVED_*_ACTIONS` map of its record type in `urls.py`, which redirects to the console form or panel.

## Read when needed

- `frontend/src/design.md`: quill component choice and states. Read it before you change a template.
- `packages/quill/packages/primitives/AGENTS.md`: the markup and attributes of each quill primitive. Read it before you add a quill class to a template.
