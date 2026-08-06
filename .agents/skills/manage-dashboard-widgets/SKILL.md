---
name: manage-dashboard-widgets
description: >
  Guides PostHog engineers through dashboard widget platform work — ship a new
  widget_type (WIDGET_REGISTRY, catalog, run_widgets, WidgetCard) or update a shipped
  type (config, query, layout, RBAC, tile filter bar, list footer, titleHref, throttles).
  Use for WidgetSpec, widget_specs/, widget-configs.zod.ts, hogli build:openapi,
  error_tracking_list, session_replay_list, widgetFilters, formatWidgetListCountFooter,
  widget_query_throttle, or WidgetCard composition. New types need widget-intake confirmation
  first. Not for MCP batch-add of existing types or adding tiles to a dashboard.
---

# Managing dashboard widgets

For **PostHog engineers** working on dashboard **widget tiles** in the repo.

Human overview: [`products/dashboards/CONTRIBUTING.md`](../../../products/dashboards/CONTRIBUTING.md)

**In scope:** widget tiles (`widget_id` on `DashboardTile`) — ship new types or change shipped types.

**Out of scope:** adding an existing type to a dashboard (MCP `dashboard-widget-catalog-list` → `dashboard-widgets-batch-add`); insight tiles, text cards, button tiles.

## 1. Route first

| Request                                                                | Path       | Start here                                                                                                      |
| ---------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------- |
| New **`widget_type`** that does not exist                              | **Ship**   | [§2 Ship a new type](#2-ship-a-new-widget_type) — intake mandatory                                              |
| Change a **shipped** type (config, query, UI, layout, RBAC, deprecate) | **Update** | [§3 Update a shipped type](#3-update-a-shipped-type) — skip intake                                              |
| Add existing type to a dashboard                                       | —          | MCP only — not this skill                                                                                       |
| **Chart / trend / graph** for product metrics on a dashboard           | —          | **Insight tile** — [architecture.md § Charts](references/architecture.md#charts--use-insight-tiles-not-widgets) |

Shipped types (code truth): [architecture.md § Shipped types](references/architecture.md#shipped-types-source-of-truth).

## 2. Ship a new widget_type

### Intake — ask before coding

**Mandatory for new types only.** Read [widget-intake.md](references/widget-intake.md) and:

1. [Discover product UI in the repo](references/widget-intake.md#discover-product-ui-in-the-repo) — concrete components/scenes before generic tile-body questions.
2. Apply [defaults and inference](references/widget-intake.md#defaults-and-inference) (`groupId`, copy spine, list UX) — never AskQuestion banned topics.
3. [Resolve ambiguity](references/widget-intake.md#resolve-ambiguity-ask-dont-guess) — one batched follow-up for gaps, max 6 questions ([open fields](references/widget-intake.md#open-fields-may-need-questions)).
4. Post the [spec table](references/widget-intake.md#spec-fields-to-lock); get confirmation before checklist §1.

### Execute

After spec confirmation → [checklist-new-widget-type.md](references/checklist-new-widget-type.md) **§1 → §8**. §5b (dedicated stories — required before the PR, not a follow-up) is sequenced once MVP tests are green.

## 3. Update a shipped type

**Skip intake.** Identify the type from the request or `EXPECTED_WIDGET_TYPES` in `widget_registry.py`.

1. Read [managing-existing-widgets.md](references/managing-existing-widgets.md) — **"What kind of change?"** routing table for primary files.
2. Confirm: which type, what changes, backward-compatible config migration?
3. Follow linked references from that table — do not re-read the new-type checklist.

**Cannot change in place:** `widget_type` string on existing rows; stored `w`/`h` when catalog defaults change.

**New visualization kind** = ship ([§2](#2-ship-a-new-widget_type)). **Chart-primary** = insight tile ([architecture.md § Charts](references/architecture.md#charts--use-insight-tiles-not-widgets)).

## 4. Platform invariants

Both paths:

1. **RBAC registry-driven** — no `widget_type` branches in `dashboard.py`. [permissions-and-sharing.md § Product RBAC](references/permissions-and-sharing.md#product-rbac)
2. **One `widget_type` everywhere** — registries + both catalogs + FE registry; variants share `groupId` only.
3. **Per-type code in product paths** — not platform shells. [architecture.md § Platform files](references/architecture.md#platform-files--do-not-branch-per-type)
4. **WidgetCard compound pattern** — [composition.md](references/composition.md)
5. **Config contract = Pydantic SSOT** — `widget_specs/configs.py` + `WidgetSpec` in `registry.py`; `hogli build:openapi` for OpenAPI/FE Zod/MCP. Runtime PATCH stays `JSONField`. See [config-and-codegen.md](references/config-and-codegen.md).
6. **No chart-primary widgets** — [architecture.md § Charts](references/architecture.md#charts--use-insight-tiles-not-widgets)

New `widget_type` strings need **no migration** — register registries + catalogs only.

## 5. Companion skills

| Skill                          | When                                                                            |
| ------------------------------ | ------------------------------------------------------------------------------- |
| `improving-drf-endpoints`      | dashboard `@extend_schema` (config serializers auto-derive from `WIDGET_SPECS`) |
| `writing-kea-logics`           | `edit*WidgetModalLogic.ts` or `dashboardLogic.tsx`                              |
| `django-migrations`            | `DashboardWidget` / `DashboardTile` schema only                                 |
| `adopting-generated-api-types` | Tile PATCH in `frontend/utils.ts`                                               |

## 6. Verify

**MVP smoke (renders + core tests — not a ship point):**

```bash
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/frontend/widgets/registry.test.tsx
```

**Ship gate (required before the PR):** [checklist §8](references/checklist-new-widget-type.md#8-tests) + `hogli build:openapi` + dedicated Storybook stories per [checklist §5b](references/checklist-new-widget-type.md#5b-storybook) (component + edit modal — required, not just the catalog overview).

**Config SSOT changes** (also run after `widget_specs/` edits):

```bash
hogli test products/dashboards/backend/api/test/test_widget_config_schema_parity.py
hogli test products/dashboards/frontend/widgets/widgetConfigSchemaParity.test.ts
hogli test products/dashboards/backend/api/test/test_widget_openapi_enums.py   # new widget_type only
```

**Update:** tests for layers touched — at minimum `test_run_widgets.py` if BE changed, `products/dashboards/frontend/widgets/` if FE changed, `hogli build:openapi` if config OpenAPI changed. See [managing-existing-widgets.md](references/managing-existing-widgets.md) routing table **Also check** column.

## Reference appendix

| Topic                      | Doc                                                                               |
| -------------------------- | --------------------------------------------------------------------------------- |
| Intake (new types only)    | [widget-intake.md](references/widget-intake.md) — canonical defaults + spec recap |
| New type checklist         | [checklist-new-widget-type.md](references/checklist-new-widget-type.md)           |
| Update shipped type        | [managing-existing-widgets.md](references/managing-existing-widgets.md)           |
| Architecture               | [architecture.md](references/architecture.md) — file map, invariants              |
| Config + codegen           | [config-and-codegen.md](references/config-and-codegen.md)                         |
| WidgetCard / edit modal    | [composition.md](references/composition.md)                                       |
| List footer / tile filters | [list-widget-patterns.md](references/list-widget-patterns.md)                     |
| Tile min/max               | [layout-and-ux.md](references/layout-and-ux.md)                                   |
| RBAC / sharing             | [permissions-and-sharing.md](references/permissions-and-sharing.md)               |
| Setup gates                | [availability-and-gating.md](references/availability-and-gating.md)               |
| MCP after ship             | [mcp.md](references/mcp.md)                                                       |
| Skill doc maintenance      | [skill-maintenance.md](references/skill-maintenance.md)                           |
