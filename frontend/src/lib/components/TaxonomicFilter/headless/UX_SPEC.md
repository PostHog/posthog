# Taxonomic filter — UX spec

Source of truth for the dropdown-menu-fronted taxonomic filter. Edit this
doc to lock the design, then rebuild fresh against it. No hooks-based
plumbing required — keep state local where it lives, pass refs/callbacks
when components have to coordinate.

---

## High-level flow

```text
[ trigger button ]
       │  click
       ▼
┌─────────────────────────────┐
│ DropdownMenu                │
│  ─ New filter…              │ → opens combobox (search across all groups)
│  ─ Recent                   │ → opens combobox seeded to "recent"
│  ─ Pinned                   │ → opens combobox seeded to "pinned"
│  ─ ─────────────            │
│  ─ Data warehouse tables  ▶ │ → submenu: list of tables → on pick, open
│                             │   inline DWH config (id / timestamp / distinct)
│  ─ HogQL expression         │ → submenu / page: SQL editor → commit on save
└─────────────────────────────┘
```

The dropdown is the **first thing** the user sees. It surfaces the most
common quick-actions (Recent / Pinned) without forcing a search step, and
hides power-user options (DWH / HogQL) inside a focused sub-flow so
they're one click away but don't clutter the combobox.

---

## Trigger

- One button, label = current selected entry's friendly name, or `"Filter"` (or
  consumer-supplied) when nothing is selected.
- Click → opens the dropdown menu. Nothing else.
- Keyboard: Enter / Space when focused opens the menu. Esc closes.

The trigger is a regular button — no compose-with-popover-trigger trick,
no anchor games. Both the dropdown menu AND the combobox popover anchor
to this button (the combobox via `Popover.Positioner` `anchor` prop using
the trigger's ref).

---

## Dropdown menu items

| Item                        | Behavior                                                                                                                                                                                           |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **New filter…**             | Closes menu, opens combobox. Combobox starts on the "All" category, search input focused, list shows everything.                                                                                   |
| **Recent**                  | Closes menu, opens combobox **drilled into the Recent category** (doesn't show chips). List shows recent entries. Search filters within recent. Show header with name, back button to dropdownmenu |
| **Pinned**                  | Same as Recent, but for the Pinned category. Doesn't show chips, Show header with name, with back button to dropdownmenu .                                                                         |
| ─ separator ─               |                                                                                                                                                                                                    |
| **Data warehouse tables ▶** | Submenu (chevron). Hover/click opens it. Show header with name, with back button to dropdownmenu                                                                                                   |
| **HogQL expression**        | Closes menu, opens HogQL editor _directly_ (skips the combobox). On save, commits the expression as the selection. Show header with name, with back button to dropdownmenu                         |

### Conditional rendering

- **Recent** / **Pinned**: only render when there are entries to show. If
  the user has zero pinned items, omit the row entirely (don't show an
  empty section).
- **Data warehouse tables**: only render when the consumer's
  `taxonomicGroupTypes` includes `DataWarehouse`.
- **HogQL expression**: only render when the consumer's
  `taxonomicGroupTypes` includes `HogQLExpression`.

These two groups (`DataWarehouse`, `HogQLExpression`) are **removed from
the combobox's category chips and item list** when surfaced via the
menu — the user gets to them through one menu, not two.

---

## Data warehouse submenu

Hover (or arrow-right) on the menu item opens a **submenu** listing
available tables (e.g. `extended_properties`, `paid_bills`, `signups`).

On clicking a table:

1. Submenu closes
2. Main menu closes
3. **Inline DWH config form** opens — same chrome as the combobox popover
   (anchored to trigger), but with a header `< Configure data warehouse
table` and the form body (ID field / Timestamp field / Distinct ID
   field selects + Cancel / Select buttons).
4. Save → commits the entry with the chosen columns merged into `item`.
5. Cancel / Esc / `<` back → closes the form, returns to root popover
   state (or closes everything if reached via the menu).

Submenu nav: arrow keys cycle tables. Enter to pick. Esc to back out to
parent menu.

---

## HogQL expression flow

Click "HogQL expression" → menu closes → **expression editor opens**
directly (no combobox stop-over). Editor is the same inline view-stack
page as DWH (header with back button, body = SQL textarea / Monaco,
footer with Cancel / Save).

Save → commits `{ name: <expression>, value: <expression> }` and closes.
Cancel / Esc → closes without committing.

---

## Combobox popover

Reached from "New filter…", "Recent", "Pinned", or after the user picks
a Recent/Pinned shortcut that doesn't immediately commit (e.g. category
drill).

- Search input at top — focused on open.
- Category chips below — `All` plus one per visible group (excluding
  Recent / Pinned / Suggested / DataWarehouse / HogQLExpression — all
  surfaced via the menu). Click chip to filter list. Tab cycles chips.
- Result list — single-cell rows by default. Each row shows
  - friendly title (or raw name)
  - `[GROUP NAME]` badge — only in the `All` category (redundant when
    drilled)
  - subtitle (raw name) when it differs from friendly
  - hover popover (preview card / tooltip) with description / type /
    sent-as / pin button — opt-in per group via consumer config
- Footer / chrome — none. Esc closes; clicking outside closes.

Click a row → commits the entry, closes popover.

### View stack inside popover

Sub-pages slide in from the right with the same chrome as the root view:

- Header gets a `<` back button + page title
- Sub-page body fills the popover envelope
- Esc / back button → pops to root

Only DWH config and HogQL editor live here. (Property "View details"
sheet was prototyped but parked.)

---

## Sizing & position

- Popover height is **fixed** (`h-[400px]`) so view-stack swaps
  (root → sub-page → root) don't reflow Floating UI's positioning.
- Width = `--anchor-width` (matches trigger width), `min-w-[320px]`.
- List inside scrolls; surrounding chrome (header, input, chips) is
  pinned.
- Position recomputed once on open; pinned thereafter.

---

## Selection behavior

- `selectedEntry` lives on the picker (controlled or uncontrolled).
- Trigger reflects the latest selection's friendly name.
- Recent + Pinned items in the menu are direct shortcuts — clicking
  commits without entering the combobox.
- Clearing selection: trigger may render a × affordance, or consumer
  handles via separate button.

---

## Keyboard summary

| Context  | Key                  | Action                             |
| -------- | -------------------- | ---------------------------------- |
| Trigger  | Enter / Space        | Open menu                          |
| Menu     | ↑/↓                  | Navigate items                     |
| Menu     | → on submenu trigger | Enter submenu                      |
| Menu     | Enter                | Activate item                      |
| Menu     | Esc                  | Close menu                         |
| Combobox | Type                 | Filter list                        |
| Combobox | ↑/↓                  | Navigate rows                      |
| Combobox | Enter                | Commit highlighted row             |
| Combobox | Tab / Shift+Tab      | Cycle category chips               |
| Combobox | Esc (drilled)        | Back to All                        |
| Combobox | Esc (root)           | Close popover                      |
| Sub-page | Esc / `<`            | Back to root view                  |
| Sub-page | Tab                  | Cycle within form (loops on edges) |

---

## What we are NOT building (yet)

- Property "View details" sheet (description / pin / edit / open) —
  parked. Hover popover may surface this later.
- Multi-select in the combobox — out of scope.
- Sticky search input across categories — input clears on chip change.
- Nested sub-menus beyond DWH tables — flat menu otherwise.

---

## Implementation notes (for the rebuild)

- **No global hooks for menu/sub-page registration.** Components
  coordinate via props + refs passed from a thin parent that owns the
  open state machine.
- **One open-state machine** at the parent level — discriminated union
  is fine: `{ kind: 'closed' } | { kind: 'menu' } | { kind: 'combobox', drillTo?: GroupType } | { kind: 'dwh-config', table } | { kind: 'hogql-edit' }`. Transitions are explicit.
- **Trigger button ref** — single ref, shared between menu (anchors via
  base-ui `DropdownMenu`'s own trigger registration) and combobox
  (anchors via `Popover.Positioner` `anchor` prop). Don't compose two
  trigger components on one button.
- **Menu and combobox never open simultaneously.** Closing the menu and
  opening the combobox happens in the same state transition.
- **DWH / HogQL data is consumer-supplied** — no kea coupling inside the
  widget. The picker takes `dataWarehouseTables: Array<{ name, fields }>`
  and `onCommit(entry)`; consumer wires kea selectors externally.
- **Recent / Pinned data**: same — passed in as `recent: Entry[]`,
  `pinned: Entry[]` props (consumer reads from whatever logic).
