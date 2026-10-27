---
name: posthog-platform-ux
description: Use when building new UI, editing existing UI, or when a task asks to simplify or redesign a surface. Covers the platform UX rules that decide what a surface shows and when, and the surfaces only the platform UX team changes. Applies to LemonUI and Quill alike.
---

# Platform UX at PostHog

The platform UX team owns this file. Ask in `#team-platform-ux` before you change a rule here.

This file decides _what_ a surface shows and _when_.
[`design.md`](./design.md) decides _how_ it looks on Quill: components, tokens and states.
Read both for UI behind `today-rail-nav`, in MCP apps and in PostHog Desktop.
Elsewhere in the web app, these rules apply on LemonUI.

## When to read this

- You build new UI.
- You edit existing UI, including a single menu, form, toolbar or settings panel.
- A task asks to "simplify" a UI, or to "redesign" any surface.

Apply each rule to what you touch.
When you edit a surface that breaks a rule, fix the part you touch and note the rest in the PR description.
Do not restructure a whole scene that the task does not cover.

## Rule 1 — Progressive disclosure

Show the controls most people need.
Put the rest one step away, behind a clear "More" or "Advanced" entry.
People who need more control dig deeper; everyone else is not overwhelmed.

### Menus and lists of actions

- Show at most 7 items at the top level, and aim for 5.
- Order items by how often people use them. The most common action comes first.
- Put the remaining items in a "More" submenu or section at the end.
- Keep destructive actions (delete, archive, revoke) last, after a separator. They can live inside "More" when they are rare.
- Do not hide the primary action of a surface. If most people come to do it, it stays visible.

### Toolbars and scene actions

- Show one primary button and at most 2 secondary buttons.
- Put every other action in an overflow menu (a `…` icon button labeled "More actions").

### Forms and settings

- Show the fields that most people set. Give every other field a sensible default.
- Put the rest in a collapsed "Advanced options" section below the basic fields.
- When an advanced field has a value other than its default, show that in the collapsed header (for example a count badge), so no one misses a non-default setting.

### Filters, columns and options

- Show the common filters or columns by default. Let people add the rest through an "Add filter" or "Configure columns" control.
- Do not show every available option as a row of chips or checkboxes.

### Don't

- Don't hide something just to reach a number. If an item is used about as often as the visible ones, rethink the grouping instead.
- Don't nest more than one level deep. "More" inside "More" means the grouping is wrong.
- Don't label the hidden area vaguely. "More", "More actions" and "Advanced options" are fine. "Other" and "Misc" are not.
- Don't move an existing item behind "More" without checking its usage first. A frequently used item that moves breaks muscle memory.

### Components

| Pattern                     | LemonUI (flag off)                                    | Quill (`today-rail-nav`, MCP apps, Desktop) |
| --------------------------- | ----------------------------------------------------- | ------------------------------------------- |
| "More" in a menu            | `LemonMenu` item with nested `items` (a submenu)      | `DropdownMenuSub`                           |
| Overflow menu on a toolbar  | `LemonMenu` with a `LemonButton` icon trigger         | `DropdownMenu` with a `Button` icon trigger |
| Collapsed "Advanced" fields | `LemonCollapse`                                       | `Collapsible`                               |
| Show the rest of a list     | A "Show N more" `LemonButton` below the visible items | A "Show N more" `Button` below the items    |

## Rule 2 — The nav rail belongs to the platform UX team

The nav rail is the column of icons at the left edge of the web app behind `today-rail-nav`.
It holds Home, Chats, Analytics, Products, More, Settings and the account menu.
The platform UX team owns it.
Only that team changes it.

### Why the rail is locked

The rail is how people break down what they want to do in PostHog.
Each item is a platform-wide first step, and everything else is a drill-down from one of them.
The team chooses each item with great care, and the set is as small as possible on purpose.

- Every item added to the rail competes with every other item for attention.
- On a 14-inch laptop screen, the rail must fit with space to spare. It never fills the full height and never scrolls.
- A rail that fills up or overflows overwhelms people and takes the product back to the crowded navigation the rail replaced.

Keep the rail minimal.
It is an overarching, platform-wide drill-down, not a place to promote a single product or feature.

These files make up the rail:

- `layout/today/TodayRail.tsx`
- `layout/today/TodayRailTile.tsx`
- `layout/today/todayRailItems.tsx`
- `layout/today/TodayMoreMenu.tsx`
- `layout/today/todayRailSeverity.ts` and `layout/today/todayRailStatusLogic.ts`

A change to the rail includes:

- Adding, removing, renaming or reordering a rail item, including an item in the "More" menu.
- Changing a rail icon, label, width, spacing or active state.
- Changing what a rail item opens.

Only change the rail for a person on the platform UX team.
When a task asks for a rail change, ask the person whether they are on that team.
If they are not, stop and tell them to ask in `#team-platform-ux`.
A product that wants more visibility goes in the Products pane, not on the rail.

### Proposing a change

Do not add or change a rail item without consensus and data.

- Bring the proposal to `#team-platform-ux` with usage data that shows the need.
- Get agreement from the platform UX team before you write the change.
- You can run an experiment on a rail change behind a feature flag. The platform UX team still reviews it.
- Take care with experiments here. The rail is a critical path for every user, so a bad variant hurts every product at once.

`owners.yaml` requests a review from the platform UX team on every change to these files, however small.
A PR that changes the rail needs their approval before it merges.

## Review before handoff

- Count the top-level items in every menu and toolbar you touched.
- Open each "More" and "Advanced" area and confirm that every hidden item still works with the keyboard.
- Confirm that a first-time user can finish the primary task without opening a "More" or "Advanced" area.
- Confirm that the diff does not touch a nav rail file, unless you are on the platform UX team.
