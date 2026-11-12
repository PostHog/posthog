---
name: extending-the-admin-console
description: Add or change what staff see and do in PostHog Admin, the staff console at /admin/console/. Use when adding a panel to a team page, a staff action (an operation), or a cross-team report (a tool) in a `console.py`, when moving a button, view or page out of Django admin into the console, or when asked to "add an admin action", "add a staff tool", "show X to support in admin", or to touch `posthog/admin/console/` or `posthog/templates/admin_console/`. Covers choosing panel vs tool vs Django admin, the data-only contract, copy, danger operations, replacing the old Django admin entry point, and the checks before calling it done.
---

# Extending the admin console

PostHog Admin is a shared surface. Every team adds to it, and staff use it under pressure, often while a customer waits.
Consistency is the feature: a panel that looks and reads like every other panel is one staff can use without thinking.
Read [`posthog/admin/console/AGENTS.md`](../../../posthog/admin/console/AGENTS.md) first. It holds the invariants and the add-a-panel and add-a-tool recipes. This skill holds the judgment around them.

## 1. Decide where it goes

- **Plain create, read, update or delete on one model** stays in Django admin. The console is not a second CRUD layer.
  A changelist action (`actions = (...)`) stays too when it does only what staff could do in the change form of the selected rows.
  It writes fields of those rows, shows no page of its own, and starts nothing itself: no send, job, outside call, or write to another model.
  It calls `self.log_change(request, obj, ...)` for each row, because an action leaves no admin history.
  Any other action is a console operation: classify it with section 4.
  Before you move an action for a reason or a gate, make its field read-only in Django admin too, or the move protects nothing.
- **Facts and actions about one team or one organization** go in a panel on that record's page. One panel per product concern, owned by the team that owns the data.
- **A report across many teams, or an action that is not about one record** (a backfill, a re-save across teams) is a tool. An action on one team from a tool row links to that team's page instead of becoming a tool operation.
- **A staff page your product already has in the app** (a DRF staff endpoint and scene) is legacy. Do not extend it and do not bridge to it. Ask the user whether to move it into the console as its own change.
- **Anything else** (a new record type such as a user or project page, a new block kind, a new tool group, a template change) is a shell change. Stop and ask the user: those need a review by the console owners (team-devex), not a product team alone.

## 2. Write the panel or tool as data

- Return `Fact`, `Operation` and tool blocks only. The contract rejects markup, unknown blocks and bad keys at import or render time, so fix the contribution, not the check.
- Keep the logic out of `console.py`. Facts and handlers call your product's facade or a service function, even when the product is not isolated yet. `console.py` is an adapter, like a view: no ORM queries, no `.delay()` calls, no cache clients. A small dataclass the facade returns goes where [products/architecture.md](../../../products/architecture.md) puts facade contracts.
- Show at most `MAX_FACTS_PER_PANEL` facts. Pick the ones that answer the questions staff ask in a ticket. History and long lists belong in a tool.
- Do not repeat facts another panel shows (team ID, organization, API token are in Overview).

## 3. Copy

Invoke `/writing-user-facing-copy`. In the console that means:

- Sentence case for titles, labels and buttons. Keep proper nouns and acronyms as they are (API, AI, ClickHouse).
- An operation label starts with a verb and names the effect: "Suspend email sending", not "Email" or "Submit".
- Use the words staff see in the app, not field names. "Revoked" beats `llm_gateway_revoked_at`.
- An `Operation.description` says what happens to the customer, for example "The team gets an email".

## 4. Classify every operation

- **Read only** needs no operation at all. Make it a fact.
- **Internal and reversible** (rebuild, clear or purge a cache that refills itself) is a plain operation.
- **Gives the customer something back** (enable access, clear a revoke, re-enable sending, add credit) is a plain operation. Give it a form only when it needs input, as Add credit does for the amount and the reason.
- **Takes something away from the customer, or cannot be undone** (suspend, revoke, replace a token) sets `danger=True`, takes a form with a `reason` field, and sets `undo_hint` to how staff undo it, or that they cannot. The console writes the reason to the audit log and shows the undo hint on the confirm page.
- **Only the owning team's staff may run it** (approve a deletion, send usage reports): set `gate=Gate.owner()`, and set `staff_group` on the panel or tool's `Owner` to that team's Django group. Use `Gate.group(name)` only when the operation belongs to another team's group.
- A handler that moves money or sends messages builds its idempotency key from the `form_nonce` the console posts, so a double submit runs once.
- Offer an operation only in the state where it makes sense. The console runs only operations the panel offers right now.
- A form that edits current state sets `form_initial` from the record, so an unchanged submit changes nothing.
- To report a failure, a handler adds an error message and returns a 4xx or 5xx response. For an operation with a form, the console then shows the form again with what staff typed.

## 5. Move a Django admin action without losing anyone

1. Point the operation at the old view with `AdminViewBridge(Model, SomeAdmin.view_method)` while the logic still lives in the `ModelAdmin`.
2. Replace the old button in Django admin with `MovedToConsole.action("<record>", obj, "<panel-key>", "<what moved>")`, so staff who look in the usual place find the new one.
3. When a whole page moves, declare its old path with `console.register_moved_page` in your `console.py`, which tells staff the page moved.
4. Every old URL keeps working, query parameters included. Support staff keep bookmarks to old admin pages and actions. When you delete a record action's view, declare its old path with `console.register_moved_action` in your `console.py`, so it redirects to the console form or panel. A move touches only `products/<product>/backend/`.

## 6. Before you call it done

- Test your operations in `products/<product>/backend/tests/test_console.py`: a parameterized case for each new operation's success and refusal. The shell tests in `posthog/admin/test_admin_console.py` already check from the registry that every panel renders and every moved URL reaches a registered panel or tool, so do not add cases there. A move with a `resolver` needs a product test that its lookup lands on the right record.
- Run `pnpm --filter=@posthog/frontend build:admin-console` when you add an owner crest. Commit the output.
- Open the record page (`/admin/console/teams/<id>/` or `/admin/console/organizations/<uuid>/`) on the local stack (log in as `test@posthog.com`) and look at the page at a narrow and a wide window. A panel that reads wrong in the browser is not done, whatever the tests say.
- Put a screenshot of the panel in the PR description.
