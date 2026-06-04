# Widget intake — questions before coding

Use when `/dashboard-widgets` **Path: Ship** ([SKILL.md §2](../SKILL.md#2-ship-a-new-widget_type)) — a **new `widget_type`**. Not for updates to shipped types.

## Agent workflow

1. Parse the request into [spec fields](#spec-fields-to-lock).
2. Apply [defaults from SKILL.md §2.2](../SKILL.md#22-infer--defaults).
3. Ask **one batched follow-up** for gaps — `AskQuestion` when available, else a numbered list. Max **6** questions; order: placement → query/UI → config → access.
4. Post the spec summary below and get explicit confirmation before checklist §1.

Do not open the checklist until the engineer confirms (or says "defaults fine").

## Always confirm (even when inferred)

Include in the spec recap — engineer signs off:

| Field                      | Why it matters                                        |
| -------------------------- | ----------------------------------------------------- |
| **`widget_type`**          | Immutable registry/DB key                             |
| **`groupId`**              | Add-modal section; variants share group, not type     |
| **Copy spine**             | `error_tracking_list` vs `session_replay_list`        |
| **Query runner**           | Exact function `run_*` calls — no parallel query path |
| **Variant vs new product** | New `groupId` → checklist §4c                         |

## Ask when not stated

Skip rows already answered. Cap at 6 per round.

### Product placement

1. **Add-modal group** — Variant in an existing group (which sibling?) or first widget for a new product area?
2. **Label + description** — Picker name and one-line description (not the internal `widget_type`).

### Data and UI

3. **Visualization** — List/table (default), metric, chart, or custom? (Non-list → cannot fully copy list spine.)
4. **Query source of truth** — Which existing query runner should `run_*` call?
5. **UI reuse** — `products/<product>/frontend/`, `scenes/<area>/`, or net-new in `widgets/<product>/`?
6. **Result shape** — Same as sibling `{ results: [...] }` or different?

### Config and edit modal

7. **Editable config** — Limit, sort, date range, filter test accounts, product-specific filters?
8. **Defaults** — Default limit, sort, date range when tile is first added?
9. **Hardcoded for v1** — Anything that looks configurable but should stay fixed?

### Tile chrome and layout

10. **Default size** — Match sibling `defaultLayout` or different `w`/`h`?
11. **Minimum resize** — Explicit catalog `minH`? (Platform floor is 4 rows.)
12. **Header "View" link** — `titleHref` to a product scene?

### Access, setup, limits

13. **Product RBAC** — Same `productAccess` as sibling or different?
14. **Setup before data** — Project prerequisite? Catalog `availability` vs inline gate in `Component` ([availability-and-gating.md](availability-and-gating.md)).
15. **Listing throttles** — Same as standalone product API (replay pattern)?
16. **Denied access copy** — Generic lock or custom message?

### Sharing and agents

17. **Public/shared dashboards** — Default placeholder or custom **`sharedPlaceholder`**?
18. **MCP catalog copy** — Extra `config_schema_hints` beyond validate defaults?

### Defer to Phase 2 (mention, do not block v1)

Storybook, overview fixtures, OpenAPI/MCP regen — after MVP tests unless engineer asks.

## Spec fields to lock

Post this block for confirmation:

```text
widget_type:
groupId:
label / description:
copy_from: error_tracking_list | session_replay_list
run_* delegates to:
UI imports from:
config fields:
defaults:
defaultLayout (w, h, minW, minH):
productAccess:
setup gating: none | catalog availability | inline Component gate
availability_requirements (BE MCP):
sharedPlaceholder: default | custom
titleHref: none | <path>
throttles: none | same as <product API>
```

Example:

```text
widget_type: error_tracking_trends
groupId: error_tracking
label / description: Issue trends / Rolling trend of top issues
copy_from: error_tracking_list
run_* delegates to: products.error_tracking.backend... (same as list)
UI imports from: products/error_tracking/frontend/ (new chart wrapper)
config fields: limit, dateRange, filterTestAccounts
defaults: limit 10, dateRange -7d
defaultLayout: w 6 h 4 minH 3
productAccess: error_tracking (same as list)
setup gating: inline Component gate (match ET)
sharedPlaceholder: default
titleHref: /error-tracking
throttles: none
```

## When to skip the question batch

Request already specifies product area, visualization, query source, and variant vs new group. Still post the spec recap.

## Red flags — stop and clarify

- Same `widget_type`, different config → need a **new** type
- Filters in ⋯ menu → settings modal only ([composition.md](composition.md))
- Special case in `dashboard.py` → registry-driven ([permissions-and-sharing.md](permissions-and-sharing.md))
- Frontend only → invalid; every type needs `validate_*` + `run_*`
