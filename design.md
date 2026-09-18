---
name: posthog-design
description: Use when building or changing any UI in the PostHog universe (web app, PostHog Desktop, MCP apps). Covers Quill components, tokens, decision rules, states, and review.
---

# Building UI at PostHog

## 0. Before you start
- Identify surface: web app | PostHog Desktop (Electron) | MCP app → apply matching section in §7
- Use Quill (`@posthog/quill`). Never add a parallel component or token layer; the only exceptions are listed in §2.
- Deeper component reference: `packages/quill/packages/primitives/AGENTS.md`; charts: `packages/quill/packages/charts/AGENTS.md`. This file wins where they disagree.

## 1. Priority order
1. Existing behaviour, data, and a11y
2. Host conventions (routes, state, existing scene patterns)
3. Clarity of the primary task
4. Quill consistency
5. Polish

## 2. Public API (closed list)
<!-- TODO: generate from @posthog/quill, quill-components and quill-charts exports in CI so it can't drift; emit full part names -->

### Setup
- Import components from `@posthog/quill` only, never from the `quill-*` sub-packages (exceptions: Metric, charts, see below)
- CSS, once, in the app's entry stylesheet, in this order:
    @import 'tailwindcss';
    @import '@posthog/quill/tokens.css';
    @import '@posthog/quill/base.css';
    @import '@posthog/quill/primitives.css';
    @import '@posthog/quill/tailwind.css';
- Scoped variants (`tokens.scoped.css`, `base.scoped.css`, `color-system.scoped.css`) apply tokens only under `[data-quill]`, for incremental migration (see §7 Web app)
- App root: `ThemeProvider` > `ToastProvider` > `TooltipProvider`

### Primitives (`@posthog/quill`)
Compose from the listed parts only. Part names are shown without their prefix (e.g. `Trigger` = `AlertDialogTrigger`).
- Accordion (Item, Trigger, Content)
- AlertDialog (Trigger, Content, Header, Title, Description, Footer, Close, Overlay, Portal)
- Autocomplete (Input, Trigger, Content, List, Item, Group, Label, Collection, Empty, Status, Separator, Clear, Value; useAutocompleteAnchor)
- Avatar (Image, Fallback), AvatarGroup
- Badge
- Button
- ButtonGroup (Separator, Text)
- Card (Header, Title, Description, Content, Footer), CardGroup
- Checkbox (Indicator)
- Chip (Close, Group)
- Collapsible (Header, Trigger, Content)
- Combobox (Input, Trigger, Content, List, ListFooter, Item, Group, Label, Collection, Empty, Separator, Value, Chips, Chip, ChipsInput; useComboboxAnchor)
- ContextMenu (Trigger, Content, Item, CheckboxItem, RadioGroup, RadioItem, Label, Separator, Shortcut, Group, Sub, SubTrigger, SubContent, Portal)
- Dialog (Trigger, Content, Header, Title, Description, Body, Footer, Close, Overlay, Portal)
- Dot
- Drawer (Trigger, Content, Header, Title, Description, Footer, Close, Handle, Backdrop, Portal)
- DropdownMenu (Trigger, Content, Item, CheckboxItem, RadioGroup, RadioItem, SelectAll, Label, Separator, Shortcut, Group, Sub, SubTrigger, SubContent, Portal; useDropdownMenuSelectAll)
- Empty (Header, Media, Title, Description, Content)
- Field (Label, Description, Error, Group, Set, Legend, Separator, Content, Title)
- Heading
- Input
- InputGroup (Addon, Button, Text, Input, NumberInput, Textarea)
- Item (Media, Content, Title, Description, Header, Footer, Actions, Group, Separator, Checkbox, Radio, MenuItem)
- Kbd (Group, Text)
- Label
- MenuLabel (section label for custom menu-like lists only)
- Menubar (Menu, Trigger, Content, Item, CheckboxItem, RadioGroup, RadioItem, Label, Separator, Shortcut, Group, Sub, SubTrigger, SubContent, Portal)
- NumberFieldRoot (NumberFieldGroup, NumberFieldInput, NumberFieldIncrement, NumberFieldDecrement, NumberFieldScrubArea, NumberFieldScrubAreaCursor)
- Pagination (Content, Item, Button, Previous, Next, Ellipsis; getPaginationRange)
- Popover (Trigger, Content, Arrow)
- Progress (Track, Indicator, Label, Value)
- RadioGroup (RadioGroupItem, RadioIndicator)
- ResizablePanelGroup (ResizablePanel, ResizableHandle)
- ScrollArea (ScrollBar)
- Select (Trigger, TriggerIcon, Value, Content, Item, Group, GroupLabel, Separator)
- Separator
- Skeleton, SkeletonText
- Slider
- Spinner
- Switch
- Table (Header, Body, Footer, Row, Head, Cell, Caption, Empty)
- Tabs (List, Trigger, Content)
- Text
- Textarea
- Toast: `toast()`, `anchoredToast()`, ToastProvider, ToastCard (no `<Toast>` component)
- Toggle; ToggleGroup (Item)
- Tooltip (Trigger, Content), TooltipProvider
- Providers/hooks: ThemeProvider, useTheme, DirectionProvider, useDirection
- Utility: `cn`

### Chat primitives (`@posthog/quill`; agent/conversation surfaces only)
- ChatBubbleGroup, ChatBubble (Content, Reactions)
- ChatMessageGroup, ChatMessage (Avatar, Header, Content, Footer)
- ChatMessageScrollerProvider, ChatMessageScroller (Viewport, Content, Item, Button; useChatMessageScroller*)
- ChatMarker (Icon, Content, Value)
- ChatTaskList (Trigger, Label, Count, Progress, Content), ChatTask, ChatTaskDetail
- ChatSourceList, ChatSource (Title, Url)
- ChatStream (Line)
- ChatGlobe
- Questionnaire (Item, Title, Description, Choices, Choice, ChoiceDescription, Input, Error, Progress, Actions, Previous, Next, Skip, Submit)
- ThreadItemGroup, ThreadItem (Gutter, Header, Author, Timestamp, Content, Body, Mention, Link, Attachment*, Reactions, Reaction, ReactionEmoji, Actions, Action, Replies*)

### Components (`@posthog/quill`)
- DataTable
- DatePicker, DateTimePicker (quickRanges, CUSTOM_RANGE)
- useCalendar
- Metric → import from `@posthog/quill-components/metric` only (pulls in charts)

### Charts (`@posthog/quill-charts`)
- Read `packages/quill/packages/charts/AGENTS.md` ("Choosing a chart") before using
- LineChart, BarChart, ScatterChart, ComboChart, FunnelChart, Sparkline
- TimeSeriesLineChart, TimeSeriesBarChart, TimeSeriesComboChart
- MetricCard

### Blocks
- None yet. Don't hand-build page headers, settings shells, or command palettes as if they were blocks.

### Not in Quill (temporary exceptions)
- PreviewCard → Base UI `PreviewCard` directly (https://base-ui.com/react/components/preview-card), styled only with tokens; match Popover's surface, border, and radius
- Link → the host router's Link; for button styling use `<Button render={<Link … />}>`

### Tokens
Use via Tailwind utilities (`bg-primary text-primary-foreground`, `border-border`, `rounded-md`, `shadow-sm`).

- Colour pairs (surface + `-foreground`, always used together):
    - `background` / `foreground`
    - `card` / `card-foreground` (currently equal to `foreground`; use `card-foreground` on cards so it can diverge later)
    - `muted` / `muted-foreground`
    - `primary` / `primary-foreground`
    - `destructive` / `destructive-foreground`
    - `success` / `success-foreground`
    - `warning` / `warning-foreground`
    - `info` / `info-foreground`
    - `completed` / `completed-foreground`
- Status tokens (`destructive`, `success`, `warning`, `info`, `completed`) are pale tinted surfaces; the `-foreground` is the strong colour. `bg-destructive` is not a red fill.
- `success` vs `completed`: success = positive outcome ("saved", "passed"); completed = final state ("merged", "done")
- Other surfaces:
    - `chrome`: toolbars, menubars, nav
- Text:
    - `subtle-foreground`: tertiary meta text, one step quieter than `muted-foreground`
- Interactive fills (overlay on any surface):
    - `fill-hover`, `fill-selected`, `fill-expanded`
- Lines:
    - `border`: dividers, container borders
    - `input`: form control borders
    - `ring`: focus rings
- Radius: `rounded-xs` | `-sm` | `-md` | `-lg` | `-xl` | `-2xl` | `-3xl` | `-4xl` | `-full`, all derived from `--radius` (`lg` = `--radius`); never hardcode px radii
- Animation: `animate-skeleton` | `animate-pulse-glow` (colour via `--pulse-glow-color`, defaults to primary) | `animate-horizontal-shake` (invalid input) | `animate-radar`; always respect `prefers-reduced-motion`
- Shadow: `shadow-sm` | `-md` | `-lg` (flat, border-coloured) | `shadow-line`
- Type size: `text-xxs` | `xs` | `sm` | `base` | `lg` | `xl` | `2xl`; prefer `Text` / `Heading` over raw sizes
- Font: `font-sans` | `font-mono`
- Spacing: Tailwind scale on `--spacing` (4px base); never override `--spacing` except at a deliberate density boundary
- Data viz: `--data-color-1` … `--data-color-15` (ordered categorical); `--color-graph-axis-label`, `--color-graph-axis-line`, `--color-graph-crosshair`. Charts read these; don't use them for UI.
- Theming vars (`--theme-hue`, `--theme-dark-hue`, `--theme-tint`, `--primary-light`, `--primary-dark`) are for theme configuration only.

### Never (in consuming code)
- Raw colours (hex, rgb, oklch)
- Arbitrary Tailwind values, other than multiples of the spacing scale
- Invented tokens or class names
- Styling `.quill-*` BEM classes, or reading Quill internals
- Deep imports from `quill-*` sub-packages (except Metric)

## 3. Component decision rules
- Buttons:
    - Button vs Link: performs an action → Button; changes URL → the host router's Link (use `render={<Link />}` on Button when it must look like one)
    - Icon-only: `size="icon"` (or `icon-xs` / `icon-sm` / `icon-lg`), `aria-label` required, and always wrap in a Tooltip with the same string
    - In-flight action: `loading`, not a separate spinner
    - Disabled: state the reason; tooltips work by default (`focusableWhenDisabled` is true), so don't turn it off
- Switch vs Checkbox vs Toggle:
    - setting that applies immediately → Switch
    - value submitted with a form, or multi-select → Checkbox
    - pressed state on a tool/formatting button → Toggle (groups → ToggleGroup)
- Picking a value:
    - RadioGroup: 2–5 options that should all be visible at once
    - Select: fixed options, no text input, up to ~15 items
    - Combobox: one or many values from a long or async list, filterable; multi-select shows chips; no free text
    - Autocomplete: free text with optional suggestions; search, command pickers
- Picking an action:
    - DropdownMenu: click-triggered list of actions
    - ContextMenu: right-click only; never the only path to an action
    - Menubar: persistent app-level menus
    - Never Select for actions; never restyle Buttons into menu rows (use `Item variant="menuItem"`)
- Switching views: Tabs (sections of one page; `variant="line"` for page-level) | ToggleGroup (2–4 display modes) | Select (many views, low priority)
- Text and numbers:
    - Input: single-line text
    - Textarea: multi-line or long free text
    - NumberFieldRoot: exact numeric values
    - Slider: approximate value in a bounded range; pair with NumberFieldRoot when exact values also matter
    - Always wrap form controls in `Field`
- Card vs plain layout:
    - Default: layout + spacing, no container
    - Card: a self-contained unit the user acts on or scans as a peer (entity summary, settings block)
    - Cards may contain an `ItemGroup`; never nest cards; never wrap a whole page section in a card
- Table vs Item list:
    - Table: rows share columns users compare, sort, or scan vertically (DataTable when sorting/filtering/selection is needed)
    - Item rows: heterogeneous entries (primary/secondary text + actions)
- Overlays:
    - Tooltip:
        - Short label for an icon/control; never the only source of essential info (not shown on touch, not the accessible name)
        - On icon-only buttons: `<TooltipTrigger delay={0}>`
        - Every surface needs a root `<TooltipProvider>` (Quill setup); it makes adjacent tooltips open instantly once one is visible
        - Add a local `<TooltipProvider>` only to change `delay`/`timeout` for a group (e.g. a toolbar); don't nest one per tooltip
    - Popover: non-modal, click-triggered, interactive content anchored to a trigger
    - PreviewCard: hover/focus preview of a link destination
    - Dialog: focused task that blocks the page
        - Footer: max 2 buttons; CTA last (right on desktop), variant `primary`, default size; Cancel before it
    - AlertDialog: confirm a destructive or irreversible action
        - Footer: max 2 buttons; CTA last, variant `destructive-outline` if destructive, else `primary`; default size
    - Drawer: <TODO: align purpose with primitives/AGENTS.md>
        - Always pass `swipeDirection` explicitly: `right` in LTR, `left` in RTL (`useDirection()`)
- Feedback:
    - `toast()`: floating; async/background results
    - `anchoredToast()`: transient feedback next to the trigger ("Copied")
    - Validation errors: inline `FieldError`, never a toast
- Loading and progress:
    - Skeleton / SkeletonText: default for initial content loads, matching final layout
    - Spinner: short inline waits where layout is unknown
    - Button `loading`: in-flight actions
    - Progress: only with a real measured value; never fake progress
- Small status:
    - Badge: status or count. On a button: button `relative`, Badge `absolute top-0 right-0`; counts need an accessible label
    - Chip: removable/selectable value (with ChipClose)
    - Dot: presence/state beside a text label; `pulse` only for live state
- Disclosure:
    - Collapsible: single section
    - Accordion: set of sections
- Chat components: only in agent/conversation surfaces
    - Questionnaire: questions the agent needs answered before continuing; never an ad-hoc form in chat
    - ChatTaskList: the agent's plan; never a hand-rolled checklist
    - ChatMarker: what the agent did (a note, a tool call, a group of them)
    - ThreadItem: feed-style rows (Slack-like channels); ChatBubble / ChatMessage for back-and-forth conversation

## 4. Required states
- loading → see §3 Loading and progress
- empty → Empty, with a next action where one exists; inside pickers use ComboboxEmpty / AutocompleteEmpty
- error:
    - field or section → inline message near the failure, with retry where possible
    - whole view failed to load → one page-level error with retry
- disabled → always state the reason (see §3 Buttons)
- no-permission:
    - single control → disabled + reason naming who can grant access ("Only admins can delete projects")
    - whole view → one page-level state explaining the missing access and how to request it; don't disable every control
    - action never relevant to this user → hide instead of disable

## 5. Typography, colour, spacing, motion, icons
- Text: use `Heading` (semantic level via `render={<h2 />}`, decoupled from size) and `Text`; never hand-roll `<p className="text-xs text-muted-foreground">`
- <TODO: remaining short imperative rules; link to detail files with "read when…">

## 6. Don't
- <TODO: PostHog-specific anti-patterns>

## 7. Surface specifics
### Web app (incl. migration rules)
- During migration, use the scoped CSS and add `data-quill` to the wrapper of any Quill subtree
- <TODO: migration rules>

### PostHog Desktop
- <TODO>

### MCP apps
- Dark mode also activates on `[data-theme="dark"]` (set by the MCP apps SDK's `applyDocumentTheme()`)
- <TODO>

## 8. Accessibility
- <TODO>

## 9. Review before handoff
- Render in light and dark; check narrow widths; run lint and types; fix and repeat