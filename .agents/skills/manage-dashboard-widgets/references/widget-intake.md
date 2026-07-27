# Widget intake — questions before coding

Use when `/manage-dashboard-widgets` **Path: Ship** ([SKILL.md §2](../SKILL.md#2-ship-a-new-widget_type)) — a **new `widget_type`**. Not for updates to shipped types.

## Agent workflow

1. Parse the request into [spec fields](#spec-fields-to-lock) (product area, label intent).
2. **[Discover product UI in the repo](#discover-product-ui-in-the-repo)** — before generic "what should the tile show?" questions.
3. Apply [defaults and inference](#defaults-and-inference) — includes `groupId`, copy spine, list UX (never AskQuestion banned topics).
4. **[Resolve ambiguity](#resolve-ambiguity-ask-dont-guess)** — ask plain questions for open fields; max 6 per round.
5. Post the spec summary below and get explicit confirmation before checklist §1.

Do not open the checklist until the engineer confirms (or says "defaults fine").

## Defaults and inference

Apply when confident after discovery; if ambiguous, [ask](#resolve-ambiguity-ask-dont-guess) — do not silently default.

| Derive              | Default                                                                                                                                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `widget_type`       | Unique `snake_case` from label                                                                                                             |
| `groupId`           | [Infer rules](#infer-groupid-add-modal) — same section as sibling in product area                                                          |
| Copy spine          | `error_tracking_list` → `widgets/error_tracking/` — [template rules](#infer-implementation-template)                                       |
| Copy spine (replay) | `session_replay_list` when recordings, throttles, or session RBAC                                                                          |
| Config              | List: `limit`, `orderBy`, `orderDirection`, `dateRange`, `filterTestAccounts`, optional `widgetFilters`                                    |
| List UX             | Tile filter bar on card (not edit modal); pagination footer; `titleHref` in view mode — [list-widget-patterns.md](list-widget-patterns.md) |
| RBAC                | Same `required_product_access` as sibling                                                                                                  |
| Layout              | Sibling `defaultLayout`; explicit `minH` for dense lists — [layout-and-ux.md](layout-and-ux.md)                                            |
| Setup gating        | Match sibling — [availability-and-gating.md](availability-and-gating.md)                                                                   |
| `sharedPlaceholder` | Platform default                                                                                                                           |
| Product UI          | Reuse scene list/card/empty/skeleton — [composition.md § Product visual parity](composition.md#product-visual-parity)                      |
| Chart / graph body  | **Do not ship** — [architecture.md § Charts](architecture.md#charts--use-insight-tiles-not-widgets)                                        |

## Discover product UI in the repo

**Mandatory before** inference about placement/template and before AskQuestion about tile body. The engineer names outcomes ("top logs", "recent recordings"); the agent finds **concrete** scene components and query runners already in the codebase.

### How to search

From inferred product area (`logs`, `error_tracking`, `session_replay`, …):

1. **Widget catalog** — `products/dashboards/frontend/widget_types/catalog.ts` (`DASHBOARD_WIDGET_CATALOG`, `DASHBOARD_WIDGET_GROUP_LABELS`) for existing groups and siblings.
2. **Product frontend** — `products/<product>/frontend/components/`, `.../scenes/`, exports like `*List`, `*Table`, `*Preview`, `*Row`.
3. **Legacy scenes** — `frontend/src/scenes/<area>/` when UI still lives outside `products/`.
4. **Existing widgets** — `products/dashboards/frontend/widgets/<product>/` (sibling `Component` imports).
5. **Backend query** — `products/<product>/backend/` for functions the standalone list scene calls; that becomes `run_* delegates to`.
6. **Routes** — `urls.ts` / scene constants for `titleHref` and `product UI reference` (e.g. `/error-tracking`, `/logs`).

Use LSP/grep/glob — do not guess component names.

### Build a short discovery note (for yourself)

```text
product area:
scene(s):
candidate UI components (path + what they render):
candidate run_* / API:
chart-only surfaces found? (if yes → insight redirect, not widget)
```

### Then decide

| Discovery outcome                   | Action                                                                                             |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| **One clear list/card UI** + runner | Lock for recap; infer `groupId` + template next                                                    |
| **Multiple viable UIs**             | Ask after inference — [code-grounded options](#askquestion--tile-body-from-code)                   |
| **Only chart/graph surfaces**       | Stop — [insight tile](architecture.md#charts--use-insight-tiles-not-widgets), not widget           |
| **Nothing reusable yet**            | Ask open-ended: what should the tile show + scene path or mock; do not offer generic "list vs KPI" |

## Infer groupId (add modal)

**Agent-only.** `groupId` is the **Add widget** menu section (e.g. "Error tracking", "Session replay") — not something the engineer should pick from `groupId` / "variant" jargon.

Use `catalog.ts` from [discovery](#discover-product-ui-in-the-repo) step 1.

| Situation                                 | `groupId`                                                           | Placement                                                                                                                                                                     |
| ----------------------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Same product as an existing catalog entry | Reuse that entry's **`groupId`**                                    | **Variant** — new row under the same section as siblings (e.g. another tile next to "Top issues")                                                                             |
| New product, no widget in catalog yet     | New `snake_case` id (usually product name: `logs`, `feature_flags`) | **First in group** — add label to `DASHBOARD_WIDGET_GROUP_LABELS` + BE `WIDGET_CATALOG` ([checklist §4c](checklist-new-widget-type.md#4c-first-widget-in-a-new-product-area)) |
| Request names recordings / replay         | `session_replay`                                                    | Variant if `session_replay_list` exists                                                                                                                                       |
| Request names errors / exceptions / ET    | `error_tracking`                                                    | Variant if `error_tracking_list` exists                                                                                                                                       |

State in the spec recap in **human terms**, e.g. `Add widget section: Error tracking (variant alongside "Top issues")` — not "variant in existing group".

Placement/`groupId` prompts are [banned](#askquestion--do-not-ask). Override only if the engineer explicitly names a different section.

## Infer implementation template

**Agent-only.** Which shipped widget to mirror for platform code (`validate_*`, `run_*`, edit modal, tests, `widgets/<product>/` layout). **Never** put this in AskQuestion — the engineer cares about product and tile behavior, not repo scaffolding.

| Pick                      | When                                                                                                                                                                          |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`session_replay_list`** | Session replay product area; recordings list; replay listing throttles; `session_replay` / replay RBAC; catalog needs `session_replay_enabled` or replay availability pattern |
| **`error_tracking_list`** | **Default** for everything else (error tracking variants, logs, flags, experiments, warehouse, new product areas, generic list widgets)                                       |

Override only if the engineer **explicitly** names a template in chat (e.g. "scaffold like session replay"). Otherwise state the pick in the spec recap; they can correct on confirm.

Folder map: `error_tracking_list` → `widgets/error_tracking/`; `session_replay_list` → `widgets/session_replay/`.

Template prompts are [banned](#askquestion--do-not-ask).

## Resolve ambiguity (ask, don't guess)

After discover + infer, list each [spec field](#spec-fields-to-lock) as **locked** or **open**:

```text
locked: groupId, implementation_template, …
open: which UI component (2 candidates), default sort, …
```

| Status                                 | Action                                                                |
| -------------------------------------- | --------------------------------------------------------------------- |
| **Locked** (request + discovery agree) | Put in spec recap; no question                                        |
| **Open / tie / weak signal**           | **Ask the engineer** — one clear question per gap                     |
| **Banned topic**                       | Infer per rules above; see [banned prompts](#askquestion--do-not-ask) |

### How to ask

- Use **plain chat questions** or `AskQuestion` — whichever fits. Prefer **direct prose** over jargon MCQs.
- **One concern per question** — e.g. "Should the tile use `LogsTable` or the stream view on `/logs`?" not a 6-topic form mixing placement + UI + config.
- If you are unsure, **ask** a specific question — do not offer [agent-deferral options](#askquestion--do-not-ask).
- Tile body with 2+ discovered UIs: [code-grounded AskQuestion](#askquestion--tile-body-from-code); 1 candidate → lock without asking.
- Cap **6 questions per round**; if more gaps remain, ask a second short batch before spec confirm — do not silently default ambiguous fields.

### Infer vs ask (calibration)

| OK to infer silently                                                  | Must ask                                                                |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `groupId` / add-modal section from product + catalog                  | Product area unknown after reading the request                          |
| `implementation_template` per [rules](#infer-implementation-template) | Two+ credible `run_*` sources with no default                           |
| Single discovered list UI + matching runner                           | Multiple UIs or runners — which one?                                    |
| Sibling `defaultLayout` / RBAC when variant in existing group         | Picker label/description not implied by request                         |
| `titleHref` from scene route in discovery                             | Config users care about (limit, sort, date range) when request is vague |

Do **not** post the final spec with `TBD` or guessed values on **open** rows — ask first, then recap.

## AskQuestion — tile body from code

When discovery finds **2+** candidates, prompt like:

**Title:** `Which existing product UI should this widget tile reuse?`

**Subtitle:** `Found in the repo — picks drive product UI parity and run_* wiring.`

**Options (examples — replace with your discovery):**

- `ErrorTrackingIssueList` — `/error-tracking` issues list
- `SessionRecordingPreview` — session replay playlist rows
- **Something else** — I'll describe in chat

Always include **Something else / I'll describe** so the engineer is not boxed in.

**Do not** use abstract-only options (e.g. "List/table of entities", "Card grid", "Single KPI") without naming repo components — those are agent inferences, not user choices.

If the request already names a scene or component and discovery confirms it, **skip** this question.

## AskQuestion — do not ask

**Banned prompts** (infer, discover in repo, or defer to spec recap):

- "copy spine", "implementation template", "which shipped widget to mirror"
- **Add-widget modal placement**, **`groupId`**, "variant in existing … group", "sibling of …", "first widget for new product group"
- Registry / `validate_*` / test file layout (unless engineer raised it)
- **Generic tile body taxonomy** without code discovery first — e.g. "List/table", "Card grid", "Single KPI" with no component/scene names
- "What should the tile body show?" with only abstract visualization options
- **Agent-deferral options** — "Not sure — recommend/pick from my answers", "Other…" when you could ask a specific question instead

**Do ask** (after [discovery](#discover-product-ui-in-the-repo)): anything still **open** per [resolve ambiguity](#resolve-ambiguity-ask-dont-guess) — product area, which discovered UI, tile behavior if nothing found, config, RBAC/setup. Chart-only discovery → redirect to insight, not a question.

## Always confirm (even when inferred)

Include in the spec recap — engineer signs off:

| Field                              | Why it matters                                                                                        |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **`widget_type`**                  | Immutable registry/DB key                                                                             |
| **`groupId` + Add widget section** | Agent-inferred — recap as human label + variant/first ([rules](#infer-groupid-add-modal))             |
| **Implementation template**        | Agent-inferred — state in recap ([rules](#infer-implementation-template)); engineer corrects if wrong |
| **Query runner**                   | Exact function `run_*` calls — no parallel query path                                                 |
| **Product UI reference**           | From [repo discovery](#discover-product-ui-in-the-repo) — scene + components                          |

## Open fields (may need questions)

After discover + [defaults](#defaults-and-inference), skip locked rows. Cap **6 questions per round** — see [resolve ambiguity](#resolve-ambiguity-ask-dont-guess).

| Area            | Ask when still open                                                                    |
| --------------- | -------------------------------------------------------------------------------------- |
| Placement       | Label + description for Add widget picker (not internal `widget_type`)                 |
| Data / UI       | Tile body component + scene (multiple discovery candidates); query runner if ambiguous |
| Config          | Editable fields, defaults, anything that looks configurable but should stay fixed v1   |
| Chrome / layout | `defaultLayout` / `minH` vs sibling; `titleHref` if discovery has no scene route       |
| Access          | RBAC vs sibling; setup gate pattern; throttles; custom denial copy                     |
| Sharing / MCP   | Custom `sharedPlaceholder`; extra `WidgetSpec.description` beyond `config_schema`      |

Chart-primary discovery or request → stop ([architecture.md § Charts](architecture.md#charts--use-insight-tiles-not-widgets)). Storybook, fixtures, and OpenAPI regen come **after** the MVP renders — but they are required to ship a new `widget_type`, never optional. Every new widget gets dedicated stories (component + edit modal) matching the sibling pattern; do not stop at the catalog overview story. Sequence them post-MVP, but do not skip them.

## Spec fields to lock

Post this block for confirmation:

```text
widget_type:
groupId:                    # agent-inferred
add widget section:         # DASHBOARD_WIDGET_GROUP_LABELS label
placement: variant | first_in_group
label / description:        # picker copy
implementation_template: error_tracking_list | session_replay_list
run_* delegates to:
UI imports from:
product UI reference (scene/tab/story/screenshot or “match sibling”):
product UI parity (components to reuse):
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
widget_type: error_tracking_top_by_volume
groupId: error_tracking
add widget section: Error tracking
placement: variant (alongside "Top issues")
label / description: Top issues by volume / Highest-volume error issues
implementation_template: error_tracking_list
run_* delegates to: (same runner as error_tracking_list, different default orderBy/limit)
UI imports from: products/error_tracking/frontend/ — ErrorTrackingIssueList
product UI reference: /error-tracking — issues list (default sort: occurrences)
product UI parity: ErrorTrackingIssueList, ErrorTrackingIssueListSkeleton, ErrorTrackingIngestionPrompt
config fields: limit, orderBy, orderDirection, dateRange, filterTestAccounts
defaults: limit 10, orderBy occurrences, dateRange -7d
defaultLayout: w 6 h 5 minH 3
productAccess: error_tracking (same as list)
setup gating: inline Component gate (match ET)
sharedPlaceholder: default
titleHref: /error-tracking
throttles: none
```

**Not a widget** (redirect at intake):

```text
Request: "error tracking trend chart widget"
→ Insight tile (e.g. Trends on $exception events or saved ET insight) — not a new widget_type
```

## When to skip questions

Skip the question batch only when **no open rows** remain in your locked/open list (product, UI, runner, label, config you care about). Still post the full spec recap so the engineer can correct inferences.

Partial clarity (e.g. product known, UI ambiguous) → ask **only** for the open rows, not the full checklist above.

## Red flags — stop and clarify

- **Chart-primary widget** (trend line, funnel viz, breakdown chart as the tile body) → **do not ship**; save/build an **insight** and add it to the dashboard ([architecture.md § Charts → insight tiles](architecture.md#charts--use-insight-tiles-not-widgets))
- Same `widget_type`, different config → need a **new** type
- Filters in ⋯ menu → settings modal only ([composition.md](composition.md))
- Special case in `dashboard.py` → registry-driven ([permissions-and-sharing.md](permissions-and-sharing.md))
- Frontend only → invalid; every type needs `validate_*` + `run_*`
