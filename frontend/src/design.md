---
name: posthog-design
description: Use when building or changing UI in PostHog Desktop, MCP apps, or web app UI gated behind the `today-rail-nav` feature flag. Covers Quill components, tokens, decision rules, states, and review.
---

# Building UI at PostHog

## 0. Before you start

- Web app scope (`frontend/src/`, `products/*/frontend/`): the `today-rail-nav` feature flag gates a Quill redesign of the whole web app UI, built alongside the current UI and kept behind the flag for months before it reaches users. This guide governs all UI on that flag path. The current, flag-off UI stays on LemonUI: never add Quill to it or convert it in place.
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

  ```css
  @import 'tailwindcss';
  @import '@posthog/quill/tokens.css';
  @import '@posthog/quill/base.css';
  @import '@posthog/quill/primitives.css';
  @import '@posthog/quill/tailwind.css';
  ```

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
- IconStack (Item)
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
- ChatMessageScrollerProvider, ChatMessageScroller (Viewport, Content, Item, Button; useChatMessageScroller\*)
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
  - `primary-on-foreground`: brand text, such as a link, on an inverted surface that uses `foreground` as its background (tooltips). It swaps to the other mode's brand: yellow on a dark tooltip in light mode, orange on a light tooltip in dark mode. Plain `primary` fades on those surfaces.
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
  - Icon-only: `size="icon"` (or `icon-xs` / `icon-sm` / `icon-lg`), `aria-label` required, and `tooltip` with the same string
  - Size: buttons and select or picker triggers use the default size (`size="icon"` when icon-only). Use `sm` or `xs` only for a special case, such as a dense table cell, or when the design asks for it
  - In-flight action: `loading`, not a separate spinner
  - Disabled: say why with `disabledReason`, not `disabled`. It disables the control and shows the reason in a tooltip. `Button`, every menu item, `Checkbox` and `Switch` take it. Never hand-wrap a disabled control in a Tooltip
  - Leading icon: the first child, before the label. Trailing icon: the last child
  - Indicator dot (unread, pending tasks): the Button `indicator` prop (`"default"`, or `"warning"` / `"destructive"` for a problem), never a hand-placed `span`. It sits on the top-right corner, outside the icon. Off the app background, set `--quill-button-indicator-ring` to the surface behind the button. Say what the dot means in the `aria-label`
  - Split button (main action plus a menu of variants): `ButtonGroup` holding the Button and an icon-only `DropdownMenuTrigger` with `IconChevronDown`
- Switch vs Checkbox vs Toggle:
  - setting that applies immediately → Switch
  - value submitted with a form, or multi-select → Checkbox
  - pressed state on a tool/formatting button → Toggle (groups → ToggleGroup)
- Picking a value:
  - RadioGroup: 2–5 options that should all be visible at once
  - Select: fixed options, no text input, up to ~15 items
  - Select and Combobox triggers follow the button size rule. Their popup items are always default size, so an `sm` trigger opens a menu bigger than itself. This includes a `Button` that opens a picker
  - Combobox: one or many values from a long or async list, filterable; multi-select shows chips; no free text
  - Actions in a Combobox (settings, "New …") are list items, never footer buttons. See section 8
  - Autocomplete: free text with optional suggestions; search, command pickers
- Picking an action:
  - DropdownMenu: click-triggered list of actions
  - ContextMenu: right-click only; never the only path to an action
  - Menubar: persistent app-level menus
  - Never Select for actions; never restyle Buttons into menu rows (use `Item variant="menuItem"`)
  - A menu sizes to its longest row, never narrower than its trigger. Don't set a width on `DropdownMenuContent` unless the content needs a fixed one
  - A row with a second line takes `description` on `DropdownMenuItem` or `DropdownMenuSubTrigger`. Never stack the text yourself: the row has a fixed height until `description` tells it to grow
  - A menu item that navigates calls the router in `onClick`. Never pass a Link through the item's `render`: the item already uses `render` for its row styling
  - Icon-only menu trigger: `aria-label` and a tooltip with the same string, as for any icon-only button
- A list of clickable rows (tickets, programs, recent items) → `CardGroup` of `Card size="sm"`, each holding one full-width `<button>` or `<a>`. Item has no clickable variant. `Item tone` is for callouts only, such as a warning or an incident notice
- Switching views: Tabs (sections of one page; `variant="line"` for page-level) | ToggleGroup (2–4 display modes) | Select (many views, low priority)
- Filtering a list in a compact area (a sidebar pane, a side panel, a picker inside a menu):
  - A search field (`InputGroup size="sm"`) and, beside it, one icon-only funnel button (`TodayFilterMenuTrigger`). Never a row of selects: it does not fit, and it hides which filters exist
  - The funnel opens a DropdownMenu with one row per filter: the label on the left and the choice in force on the right, opening a submenu of the options (`TodayRecentRadioSubmenu`). One choice → radio items; several → checkbox items. The default comes first ("Any user", "All")
  - While any filter differs from its default, the funnel shows a dot and reads "Filters on", and that row's value takes the primary color
  - "Clear filters" is the last row, after a separator, `variant="destructive"`, and only shows while a filter is on
  - Inside another menu (a picker), give the outer `DropdownMenu` `modal={false}`, or it blocks the filter menu's popup
  - Precedent: `layout/today/TodayViewsFilterMenu`
- Text and numbers:
  - Input: single-line text. Beside default-size buttons, such as a search field next to a filter button, use `size="sm"` on `Input` or `InputGroup` so the heights match
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
    - Text is left-aligned, never centered. For several lines, pass one `flex flex-col` child; `flex-col` on `TooltipContent` itself centers each line
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
    - Menu items never carry a Dot; show a status in a menu row with a Badge
- Disclosure:
  - Collapsible: single section
  - Accordion: set of sections
- Scrolling:
  - Default: a plain scroller with an edge fade, `overflow-y-auto scroll-mask-y-4 scroll-py-4`. This is the pattern quill's menus, Select and Combobox use. The fade is CSS only, while `ScrollArea` runs JavaScript and React state updates on every scroll
  - `scroll-py-4` keeps a keyboard-focused row clear of the fade. The mask fades the content itself, so keep sticky headers and other fixed controls outside the scroller
  - Use `ScrollArea` only when you need what it adds: custom, always-visible or hidden scrollbars (`alwaysShowScrollbars`, `hideScrollbars`), scroll-to-edge buttons (`showScrollToButton`), or a dialog body (`DialogBody` renders one by default)
  - The fade needs scroll-driven animations (Chrome, Edge, Safari 26 and later). Firefox and reduced-motion users get no fade, and the content still scrolls normally
  - The web app's Tailwind build loads `tailwindcss-scroll-mask` (`common/tailwind/tailwind.css`), so every `scroll-mask-*` utility works in app code
- Chat components: only in agent/conversation surfaces
  - Questionnaire: questions the agent needs answered before continuing; never an ad-hoc form in chat
  - ChatTaskList: the agent's plan; never a hand-rolled checklist
  - ChatMarker: what the agent did (a note, a tool call, a group of them)
  - ThreadItem: feed-style rows (Slack-like channels); ChatBubble / ChatMessage for back-and-forth conversation

## 4. Required states

- loading → see §3 Loading and progress
- empty → Empty, with a next action where one exists; inside pickers use ComboboxEmpty / AutocompleteEmpty
  - icon → `IconStack` with one `IconStackItem` per product or type it covers, colored `var(--color-product-<product>-light)`; no product → leave `color` out for grey
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
- Icons: use `IconPlus` for add and new actions, never `IconPlusSmall`. The small glyph looks undersized next to the other icons in a row of icon buttons
- Body text uses the `text-xs` size: `<Text size="xs">`. `Text` defaults to `base`, so always pass `size="xs"` for body copy
- Space a section's contents with the parent's `gap-*` (`gap-2` within a section). When a button sits beside the section's title, use `gap-1`, because the button makes the title row taller. Never give the contents, headings included, a bottom margin. The web app's global styles add margins to `h1`–`h6` and `p`, so pass `className="m-0"` on a `Heading`'s or `Text`'s `render` element
- An inline link inside a sentence uses the same text size as the sentence: `<Button variant="link" size="inline">`. The other `Button` sizes set a control height and their own font size, so they never match the text around them. Don't patch one with `h-auto p-0`
- <TODO: remaining short imperative rules; link to detail files with "read when…">

## 6. Don't

- <TODO: PostHog-specific anti-patterns>

## 7. Surface specifics

### Web app (incl. migration rules)

- The Quill UI ships behind the `today-rail-nav` feature flag; don't change the flag-off LemonUI path to match it
- During migration, use the scoped CSS and add `data-quill` to the wrapper of any Quill subtree
- Migrate a LemonUI call site by branching on the flag. Every migrated call site has the same shape, so a reader can find both halves:

  ```tsx
  const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV') // with the component's other hooks, never after a return

  <SceneTitleSection
      actions={
          todayRailNav ? (
              <Button variant="primary" render={<LinkPrimitive to={urls.x()} />} disabledReason={reason} data-attr="new-x">
                  <IconPlus />
                  New x
              </Button>
          ) : (
              <LemonButton type="primary" size="small" to={urls.x()} icon={<IconPlusSmall />} disabledReason={reason} data-attr="new-x">
                  New x
              </LemonButton>
          )
      }
  />
  ```

- Name the flag variable `todayRailNav`. The flag-off branch keeps the Lemon code, and its behavior, unchanged
- A short quill branch stays inline. A longer one, or one that needs its own hooks, goes in a `Quill<Name>.tsx` file next to the Lemon component
- Behavior is shared, never copied. A handler, dialog or menu item list that both branches need lives in one function or kea action that both call. Only the view forks
- A shared Lemon component gets a `Quill<Name>.tsx` sibling, and returns it after its last hook when the flag is on. Flags load after the first render, so a return before a hook changes the hook order and crashes. If the component also renders on surfaces outside the migration, leave it alone and let the migrated caller pick the quill sibling
- Keep every `data-attr`, handler and string. `data-attr` values are frozen
- A product that imports quill declares `"@posthog/quill": "workspace:*"` in its `package.json`, or Vite cannot resolve it
- Lemon to quill mapping:

  | Lemon                                  | Quill                                                                                                        |
  | -------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
  | `LemonButton type="primary"`           | `variant="primary"`                                                                                          |
  | `type="secondary"`                     | `variant="outline"`                                                                                          |
  | `type="tertiary"`, or no type          | `variant="default"`                                                                                          |
  | `status="danger"`                      | `variant="destructive-outline"` (`destructive` only for a primary destructive action)                        |
  | `size="small"`, `"xsmall"`, or no size | default size (omit `size`; it matches Lemon small)                                                           |
  | `icon={<IconX />}`                     | `<IconX />` as the first child                                                                               |
  | `IconPlusSmall`                        | `IconPlus`                                                                                                   |
  | `type` held in a variable              | `quillButtonVariant(type)` (`lib/lemon-ui/LemonButton/quillButtonVariant`)                                   |
  | `to={url}`                             | `render={<LinkPrimitive to={url} />}`                                                                        |
  | `disabledReason`, `tooltip`            | the same props on `Button`                                                                                   |
  | `sideAction` with a dropdown           | `ButtonGroup` (see §3 Buttons)                                                                               |
  | `LemonMenu`                            | `DropdownMenu`; nested items → `DropdownMenuSub`                                                             |
  | `LemonTag`                             | `Badge`                                                                                                      |
  | `LemonSelect`                          | `Select`                                                                                                     |
  | `LemonSegmentedButton`                 | `ToggleGroup`                                                                                                |
  | `AccessControlAction`, `Shortcut`      | keep the wrapper around the quill `Button`, menu item, `Checkbox` or `Switch`; it passes `disabledReason` in |

### PostHog Desktop

- <TODO>

### MCP apps

- Dark mode also activates on `[data-theme="dark"]` (set by the MCP apps SDK's `applyDocumentTheme()`)
- <TODO>

## 8. Accessibility

- Every action in a popup works from the keyboard alone: open the popup, reach each row with the arrow keys, and run it with Enter
- A Combobox keeps focus in its search field, so the arrow keys move only through its items and Tab never leaves the field. A Button in `ComboboxListFooter` is therefore out of reach. Put an action such as "Settings" or "New project" in the list as a `ComboboxItem`, in a last group after a `ComboboxSeparator`
  - Branch on the action's value in `onValueChange`, and keep the action out of the selected value
  - A search must never hide the actions. When a logic already filters the items, pass `filter={null}`. Otherwise pass a `filter` that always keeps the actions
  - When no other item matches, the action group's label says so. `ComboboxEmpty` never shows while the actions are in the list
  - Precedent: `layout/today/TodaySwitcherMenu` (the org and project switchers)
- Before handoff, drive each popup you touched with the keyboard only: open it, arrow to every row, and press Enter on each action

## 9. Review before handoff

- Render in light and dark; check narrow widths; run lint and types; fix and repeat
