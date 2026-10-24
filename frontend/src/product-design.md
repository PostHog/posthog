---
name: posthog-product-design
description: Use when building new UI, editing existing UI, or when a task asks to simplify or redesign a surface. Covers the product design rules that decide what a surface shows and when. Applies to LemonUI and Quill alike.
---

# Product design at PostHog

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

## Review before handoff

- Count the top-level items in every menu and toolbar you touched.
- Open each "More" and "Advanced" area and confirm that every hidden item still works with the keyboard.
- Confirm that a first-time user can finish the primary task without opening a "More" or "Advanced" area.
