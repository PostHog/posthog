---
name: posthog-design
description: Use when building or changing any UI in the PostHog universe (web app, PostHog Desktop, MCP apps). Covers Quill components, tokens, decision rules, states, and review.
---

# Building UI at PostHog

## 0. Before you start
- Identify surface: web app | PostHog Desktop (Electron) | MCP app → apply matching section in §7
- Use Quill (`packages/quill`). Never add a parallel component or token layer; the only exceptions are listed in §2.

## 1. Priority order
1. Existing behaviour, data, and a11y
2. Host conventions (routes, state, existing scene patterns)
3. Clarity of the primary task
4. Quill consistency
5. Polish

## 2. Public API (closed list)
<!-- TODO: generate this section from packages/quill exports in CI so it can't drift -->
- Components:
    - Accordion
    - AlertDialog
    - Autocomplete
    - Avatar
    - Badge
    - Button
    - ButtonGroup
    - Card
    - CardGroup
    - Chat
        - ChatBubble
        - ChatMarker
        - ChatMessage
        - ChatMessageScroller
        - ChatStream
        - ChatTaskList
        - Questionnaire
        - ThreadItem
    - Checkbox
    - Chip
    - Collapsible
    - Combobox
    - Dialog
    - Dot
    - Drawer
    - DropdownMenu
    - Empty
        - Empty
        - MenuEmpty
    - Field
    - Input
    - InputGroup
    - Item
    - Kbd
    - Label
    - Menubar
    - NumberField
    - Pagination
    - Popover
    - PreviewCard (not yet in Quill; see exceptions below)
    - Progress
    - RadioGroup
    - Resizable
    - ScrollArea
    - Select
    - Separator
    - Skeleton
    - SkeletonText
    - Slider
    - Switch
    - Table
    - Tabs
    - Textarea
    - Toast
    - Toggle
    - ToggleGroup
    - Tooltip
- Exceptions (temporary, until Quill ships them):
    - PreviewCard → use Base UI's `PreviewCard` directly (https://base-ui.com/react/components/preview-card), styled only with the tokens below; match Popover's surface, border, and radius
- Tokens:
    - Usage: Tailwind utilities, e.g. `bg-primary text-primary-foreground`, `border-border`
    - Colors (pairs): a surface token is always paired with its `-foreground`
        - background / foreground
        - card / card-foreground
        - primary / primary-foreground
        - muted / muted-foreground
        - destructive / destructive-foreground
        - success / success-foreground
        - warning / warning-foreground
        - info / info-foreground
        - completed / completed-foreground
        <!-- TODO: confirm accent / accent-tint and any other missing tokens -->
    - Colors (no pairs)
        - border
        - input
        - ring
    - `success` vs `completed`: success is a positive outcome ("saved", "passed"); completed is a final state ("merged", "done")
- Never: raw colours, arbitrary Tailwind values, invented tokens, reading Quill internals

## 3. Component decision rules
- Button vs Link: performs an action → Button; changes URL → Link (even if button-styled)
- Switch vs Checkbox vs Toggle:
    - setting that applies immediately → Switch
    - value submitted with a form, or multi-select → Checkbox
    - pressed state on a tool/formatting button → Toggle (groups → ToggleGroup)
- Picking a value:
    - RadioGroup: 2–5 options that should all be visible at once
    - Select: fixed options, no text input, up to ~15 items
    - Combobox: fixed options, filterable; more than ~15 items; no free text
    - Autocomplete: free text with optional suggestions; search, command pickers
- Picking an action: DropdownMenu (from a trigger) | Menubar (app-level menus). Never Select for actions.
- Switching views: Tabs (sections of one page) | ToggleGroup (2–4 display modes) | Select (many views, low priority)
- Text and numbers:
    - Input: single-line text
    - Textarea: multi-line or long free text
    - NumberField: exact numeric values
    - Slider: approximate value in a bounded range; pair with NumberField when exact values also matter
- Card vs plain layout:
    - Default: layout + spacing, no container
    - Card: a self-contained unit the user acts on or scans as a peer (entity summary, settings block)
    - Never nest cards; never wrap a whole page section in a card
- Table vs Item list:
    - Table: rows share columns users compare, sort, or scan vertically
    - Item rows: heterogeneous entries (primary/secondary text + actions)
- Overlays:
    - Tooltip: short label for an icon/control; never the only source of essential info
    - Popover: non-modal, click-triggered, interactive content anchored to a trigger
    - PreviewCard: hover/focus preview of a link destination
    - Dialog: focused task that blocks the page
    - AlertDialog: confirm a destructive or irreversible action
    - Drawer: longer secondary task or detail view that keeps page context
- Feedback: Toast (async/background result) | inline Field error (validation, never a toast)
- Progress: Skeleton (unknown duration, content shape known) | Progress (measurable)
- Small status: Badge (status/count) | Chip (removable/selectable value) | Dot (presence/state only, with a text label nearby)
- Disclosure: Collapsible (single section) | Accordion (set of sections)
- Chat components: only in agent/conversation surfaces
    - Questionnaire: structured agent-to-user questions; never an ad-hoc form inside a chat
    - ChatTaskList: agent progress/steps; never a hand-rolled checklist

## 4. Required states
- loading → Skeleton / SkeletonText matching final layout
- empty → Empty (MenuEmpty inside menus), with a next action where one exists
- error:
    - field or section → inline message near the failure, with retry where possible
    - whole view failed to load → one page-level error with retry
- disabled → always state the reason
    - if a Tooltip carries the reason, the control must stay focusable (`focusableWhenDisabled`)
    - otherwise show the reason as inline text
- no-permission:
    - single control → disabled + reason naming who can grant access ("Only admins can delete projects")
    - whole view → one page-level state explaining the missing access and how to request it; don't disable every control
    - action never relevant to this user → hide instead of disable

## 5. Typography, colour, spacing, motion, icons
<short imperative rules; link to detail files with "read when…">

## 6. Don't
- <PostHog-specific anti-patterns>

## 7. Surface specifics
### Web app (incl. migration rules)
### PostHog Desktop
### MCP apps

## 8. Accessibility

## 9. Review before handoff
- Render in light and dark; check narrow widths; run lint and types; fix and repeat