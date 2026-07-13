# Primitives — Agent Reference

Quick-reference for AI agents using `@posthog/quill-primitives`. Show composition, not API docs.

## Setup

```tsx
import { ThemeProvider, ToastProvider, TooltipProvider } from '@posthog/quill-primitives'

function App() {
  return (
    <ThemeProvider defaultTheme="system">
      <ToastProvider>
        <TooltipProvider>
          <YourApp />
        </TooltipProvider>
      </ToastProvider>
    </ThemeProvider>
  )
}
```

For RTL apps, wrap with `DirectionProvider` (re-exported from Base UI) — directional pieces (Collapsible chevrons, menu alignment) read it via `useDirection`.

---

## The `render` prop

Quill uses Base UI's `render` prop (not Radix's `asChild`) to change the rendered element. Pass a template element via `render` and put children on the wrapper:

```tsx
// Correct — render is the element template, children on the wrapper
<DialogTrigger render={<Button />}>Open</DialogTrigger>

// Also correct — pass props to the template
<PopoverTrigger render={<Button variant="outline" />}>Open</PopoverTrigger>
```

Only use the self-closing pattern when you need full control over the element and its children:

```tsx
// Rare — bypasses Base UI's children merging
<PopoverTrigger render={<Button onClick={() => custom()}>Fixed text</Button>} />
```

Base UI automatically merges event handlers, aria attributes, and `data-*` state onto the rendered element.

---

## Choosing a component

Pick by intent, not appearance. Each cluster below lists the discriminating question first.

### Menus and pickers

**Is the user performing an action, or choosing a value?** Actions → menu family. Values → picker family.

| Component    | Use when                                                                                                  | Not for                                     |
| ------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| DropdownMenu | Click-triggered list of actions (edit, duplicate, delete, export). Checkbox/radio items for view options. | Choosing a form value — use Select/Combobox |
| ContextMenu  | Same as DropdownMenu but right-click triggered, no visible trigger                                        | Primary navigation (undiscoverable)         |
| Menubar      | Persistent horizontal bar of dropdown menus (scene menu bars, File/Edit/View)                             | A single one-off menu — use DropdownMenu    |
| Select       | Pick one value from a short, static list (< ~15 options), no search needed                                | Long or async lists — use Combobox          |
| Combobox     | Pick one or many values from a long/dynamic list, with search. Multi-select renders chips                 | Action menus                                |
| Autocomplete | Search-first text input with suggestions where the typed text itself is the value                         | Constrained choices — use Select/Combobox   |

For a custom menu-like list inside a Popover (when DropdownMenu's open/close semantics don't fit), use `Item variant="menuItem"` with `ItemMenuItem`/`ItemCheckbox`/`ItemRadio` — don't restyle Buttons into menu rows. `MenuLabel` is the shared section-label primitive the menu families render internally (DropdownMenuLabel, ComboboxLabel); it's exported for these custom menu-like lists.

### Disclosure

**One section or a coordinated set? Hiding content or switching between views?**

| Component   | Use when                                                                                                                                                                                                                                       |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Accordion   | A coordinated set of sections (`type="single" collapsible` or `type="multiple"`) — FAQs, grouped settings                                                                                                                                      |
| Collapsible | One standalone disclosure — "show more", advanced options, tree nodes (`variant="folder"`). For rows where only the chevron should toggle (label is a link, trailing count/actions), use `CollapsibleHeader` + `<CollapsibleTrigger iconOnly>` |
| Tabs        | Exactly one of N views visible at all times; content never fully hidden — `variant="line"` for page-level sections                                                                                                                             |

### Overlays

**Does it block the page? Does it contain interactive content? Is it anchored to a trigger?**

| Component   | Use when                                                                                                                                |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Dialog      | Modal, blocking flow — focused forms, multi-step content. `size="wide"`/`"full"` for big content                                        |
| AlertDialog | Confirmation that must be resolved — destructive/irreversible actions. Backdrop clicks never dismiss, no X button, `role="alertdialog"` |
| Drawer      | Mobile-first slide-up sheet; touch contexts                                                                                             |
| Popover     | Non-modal panel anchored to a trigger, with interactive content (filters, pickers)                                                      |
| Tooltip     | Hover-only text hint; never interactive content, never essential information                                                            |
| Toast       | Async outcome notification (`toast.success({ title })`) — fire and forget                                                               |

### Status and labels

| Component | Use when                                                                   |
| --------- | -------------------------------------------------------------------------- |
| Badge     | Semantic status text — variants info/warning/success/completed/destructive |
| Chip      | Removable token (selected tags, active filters) — pair with ChipClose      |
| Dot       | Tiny presence/status indicator next to text; `pulse` for live state        |
| Kbd       | Keyboard shortcut display, with KbdGroup for combos                        |

### Form controls

| Component   | Use when                                                                          |
| ----------- | --------------------------------------------------------------------------------- |
| Checkbox    | Independent on/off choices submitted with a form                                  |
| Switch      | Setting that takes effect immediately (no submit)                                 |
| RadioGroup  | One-of-few where all options should be visible (≤ ~5)                             |
| Select      | One-of-many where options can hide behind a trigger                               |
| Toggle      | Pressed/unpressed tool state (e.g. bold); ToggleGroup for exclusive or multi sets |
| NumberField | Numeric input with increment/decrement; Slider when the range matters visually    |
| Textarea    | Multi-line free text — a styled `<textarea>`, same conventions as Input           |

Always wrap form controls in `Field` (see Composition Patterns below).

### Text

| Component | Use when                                                                                                |
| --------- | ------------------------------------------------------------------------------------------------------- |
| Heading   | Section/page titles — sizes 2xl/xl/lg/base/sm, semantic level via `render={<h1 />}` decoupled from size |
| Text      | Body copy — sizes lg/base/sm/xs/xxs, variants default/muted/destructive, weights normal/medium/semibold |
| Label     | `<label>` bound to a control; inside forms prefer FieldLabel                                            |

Don't hand-roll `<p className="text-xs text-muted-foreground">` when `<Text size="xs" variant="muted">` exists.

### Lists and containers

**Card vs Item** — see the dedicated section below. Third option: **Table** when data is columnar and comparable across rows (sorting, sticky columns); **ItemGroup** when rows are entities with a title/description/actions shape; **Card** when each entry is a rich standalone tile.

---

## Component Catalog

| Component    | Variants                                                 | Sizes                                                | Notes                                                                                                                  |
| ------------ | -------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Button       | default, primary, outline, destructive, link, link-muted | default, xs, sm, lg, icon, icon-xs, icon-sm, icon-lg | `loading` overlays a centered spinner and disables the button (width stays stable)                                     |
| Badge        | default, info, destructive, warning, success, completed  | —                                                    | Semantic status                                                                                                        |
| Toggle       | default, outline                                         | default, sm, lg, icon                                |                                                                                                                        |
| Chip         | outline                                                  | sm                                                   | Use with ChipClose                                                                                                     |
| Separator    | —                                                        | —                                                    | orientation: horizontal/vertical                                                                                       |
| Spinner      | —                                                        | —                                                    | SVG, accepts svg props                                                                                                 |
| Skeleton     | —                                                        | —                                                    | Pulsing placeholder div                                                                                                |
| SkeletonText | —                                                        | —                                                    | lines, minWidth, maxWidth                                                                                              |
| Progress     | —                                                        | —                                                    | value: 0-100                                                                                                           |
| Slider       | —                                                        | —                                                    | value, min, max                                                                                                        |
| Avatar       | —                                                        | lg, default, sm, xs                                  | Compose `Avatar > AvatarImage + AvatarFallback`; image errors fall back to initials/icon                               |
| AvatarGroup  | —                                                        | default, sm, xs                                      | Row of Avatars; `stacked` overlaps + spreads on hover (no reflow), `reverse` spreads left; `size` forwards to children |

---

## Card vs Item — when to use which

|                     | Card                        | Item                        |
| ------------------- | --------------------------- | --------------------------- |
| **Focus**           | Visual impact, rich data    | Structure, efficiency       |
| **Structure**       | Header, Content, Footer     | Title, Description, Actions |
| **Layout**          | Tiles/grid                  | Vertical/horizontal lists   |
| **Content density** | High (media, buttons, text) | Low/medium (text, icon)     |

**Use Card** for rich, grouped content that needs a distinct visual border or shadow — product grids, dashboard widgets, user profile cards, settings panels with multiple controls.

**Use Item** for compact, scannable lists where space efficiency matters — file lists, notification items, navigation menus, settings entries.

Cards can contain Items — use `ItemGroup` inside `CardContent` for a card with a list inside it.

```tsx
{
  /* Card with an item list inside */
}
;<Card>
  <CardHeader>
    <CardTitle>Team members</CardTitle>
  </CardHeader>
  <CardContent>
    <Field>
      <FieldLabel>Members</FieldLabel>
      <ItemGroup combined>
        <Item
          variant="pressable"
          render={
            // eslint-disable-next-line react/forbid-elements
            <a href="#">
              <ItemMedia variant="icon">
                <UserIcon />
              </ItemMedia>
              <ItemContent>
                <ItemTitle>Alice</ItemTitle>
                <ItemDescription>Admin</ItemDescription>
              </ItemContent>
            </a>
          }
        />
        <Item
          variant="pressable"
          render={
            // eslint-disable-next-line react/forbid-elements
            <a href="#">
              <ItemMedia variant="icon">
                <UserIcon />
              </ItemMedia>
              <ItemContent>
                <ItemTitle>Bob</ItemTitle>
                <ItemDescription>Member</ItemDescription>
              </ItemContent>
            </a>
          }
        />
      </ItemGroup>
    </Field>
  </CardContent>
</Card>
```

---

## Composition Patterns

### Card

```tsx
<Card>
  <CardHeader>
    <CardTitle>Title</CardTitle>
    <CardDescription>Description</CardDescription>
  </CardHeader>
  <CardContent>{/* content */}</CardContent>
  <CardFooter>
    <Button>Action</Button>
  </CardFooter>
</Card>
```

Stack cards with merged borders:

```tsx
<CardGroup>
  <Card>...</Card>
  <Card>...</Card>
</CardGroup>
```

`size="sm"` tightens the card's gap + block padding (`0.75rem`). `flush` lets a full-bleed child (a `Table`, a chart) run corner to corner: it drops the card's section gap + bottom padding and the `CardContent`'s inline padding, while the header keeps its own padding + divider. Use it instead of hand-writing `gap-0 pb-0` on the Card and `p-0` on the CardContent.

```tsx
<Card flush>
  <CardHeader>
    <CardTitle>Revenue</CardTitle>
  </CardHeader>
  <CardContent>{/* Table / chart runs to the card edges */}</CardContent>
</Card>
```

For a stat tile (headline number + change pill + sparkline), don't hand-build one in a `Card` — wrap `Metric` (from `@posthog/quill-components/metric`) in `<Card flush>`. See its section in `../components/AGENTS.md`.

### Field (forms)

Always use Field for form controls, not raw Label + Input:

```tsx
<Field>
  <FieldLabel htmlFor="name">Name</FieldLabel>
  <Input id="name" placeholder="Enter name" />
  <FieldDescription>Helper text</FieldDescription>
  <FieldError>Error message</FieldError>
</Field>
```

Horizontal layout:

```tsx
<Field orientation="horizontal">
  <FieldLabel htmlFor="name">Name</FieldLabel>
  <FieldContent>
    <Input id="name" />
    <FieldDescription>Helper text</FieldDescription>
  </FieldContent>
</Field>
```

Grouped fields with fieldset:

```tsx
<FieldSet>
  <FieldLegend>Account details</FieldLegend>
  <FieldGroup>
    <Field>
      <FieldLabel htmlFor="email">Email</FieldLabel>
      <Input id="email" type="email" />
    </Field>
    <Field>
      <FieldLabel htmlFor="password">Password</FieldLabel>
      <Input id="password" type="password" />
    </Field>
  </FieldGroup>
</FieldSet>
```

### Input Group (input with addons)

```tsx
<InputGroup>
  <InputGroupAddon align="inline-start">
    <InputGroupText>
      <SearchIcon />
    </InputGroupText>
  </InputGroupAddon>
  <InputGroupInput placeholder="Search..." />
  <InputGroupAddon align="inline-end">
    <InputGroupButton>
      <XIcon />
    </InputGroupButton>
  </InputGroupAddon>
</InputGroup>
```

### Checkbox / Switch

```tsx
<div className="flex items-center gap-2">
  <Checkbox id="terms" checked={checked} onCheckedChange={setChecked} />
  <Label htmlFor="terms">Accept terms</Label>
</div>

<div className="flex items-center gap-2">
  <Switch id="notifications" checked={on} onCheckedChange={setOn} />
  <Label htmlFor="notifications">Enable notifications</Label>
</div>
```

Switch has sizes: `<Switch size="sm" />` or `<Switch size="default" />`

### Select

```tsx
<Select>
  <SelectTrigger>
    <SelectValue placeholder="Choose..." />
  </SelectTrigger>
  <SelectContent>
    <SelectGroup>
      <SelectGroupLabel>Fruits</SelectGroupLabel>
      <SelectItem value="apple">Apple</SelectItem>
      <SelectItem value="banana">Banana</SelectItem>
    </SelectGroup>
    <SelectSeparator />
    <SelectItem value="other">Other</SelectItem>
  </SelectContent>
</Select>
```

Small trigger: `<SelectTrigger size="sm">`

### Combobox (searchable select)

```tsx
<Combobox>
  <ComboboxInput placeholder="Search..." />
  <ComboboxContent>
    <ComboboxList>
      <ComboboxEmpty>No results</ComboboxEmpty>
      <ComboboxGroup>
        <ComboboxLabel>Options</ComboboxLabel>
        <ComboboxItem value="one">One</ComboboxItem>
        <ComboboxItem value="two">Two</ComboboxItem>
      </ComboboxGroup>
    </ComboboxList>
  </ComboboxContent>
</Combobox>
```

Multi-select with chips:

```tsx
<Combobox>
  <ComboboxChips>
    <ComboboxChip value="a">Tag A</ComboboxChip>
    <ComboboxChip value="b">Tag B</ComboboxChip>
    <ComboboxChipsInput placeholder="Add..." />
  </ComboboxChips>
  <ComboboxContent>
    <ComboboxList>
      <ComboboxItem value="c">Tag C</ComboboxItem>
    </ComboboxList>
  </ComboboxContent>
</Combobox>
```

### Autocomplete (search-first input)

The typed text is the value; items are suggestions. Pass `items` to the root and render via function-as-children so Base UI owns the filter pipeline. For a sticky-footer "Create new" action, use Combobox (`ComboboxListFooter`) instead.

```tsx
<Autocomplete items={FRAMEWORKS} value={value} onValueChange={setValue}>
  <AutocompleteInput placeholder="Search…" />
  <AutocompleteContent>
    <AutocompleteEmpty>No matches</AutocompleteEmpty>
    <AutocompleteList>
      {(item: string) => (
        <AutocompleteItem key={item} value={item}>
          {item}
        </AutocompleteItem>
      )}
    </AutocompleteList>
  </AutocompleteContent>
</Autocomplete>
```

Grouped items: pass `items={[{ label, items }]}` shapes, render `AutocompleteGroup items={group.items}` > `AutocompleteLabel` + `AutocompleteCollection` inside `AutocompleteList`. To anchor the popup to an external trigger, pass `anchor={triggerRef}` to `AutocompleteContent`.

### Dialog

```tsx
<Dialog>
  <DialogTrigger render={<Button />}>Open</DialogTrigger>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Title</DialogTitle>
      <DialogDescription>Description</DialogDescription>
    </DialogHeader>
    {/* content */}
    <DialogFooter>
      <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
      <Button>Confirm</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

Hide close button: `<DialogContent showCloseButton={false}>`

### Alert Dialog (must-resolve confirmation)

Same shell as Dialog (shared `quill-dialog__*` styles) but `role="alertdialog"`, always modal, backdrop clicks never dismiss, and no X button — the user must pick an action (or Esc). Use for destructive/irreversible confirmations; put Cancel first so it takes initial focus.

```tsx
<AlertDialog>
  <AlertDialogTrigger render={<Button variant="destructive" />}>Delete project</AlertDialogTrigger>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Delete this project?</AlertDialogTitle>
      <AlertDialogDescription>This action cannot be undone.</AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
      <AlertDialogClose render={<Button variant="destructive" />}>Delete</AlertDialogClose>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

### Drawer (mobile-friendly)

```tsx
<Drawer>
  <DrawerTrigger render={<Button />}>Open</DrawerTrigger>
  <DrawerContent>
    <DrawerHeader>
      <DrawerTitle>Title</DrawerTitle>
      <DrawerDescription>Description</DrawerDescription>
    </DrawerHeader>
    {/* content */}
    <DrawerFooter>
      <Button>Submit</Button>
      <DrawerClose render={<Button variant="outline" />}>Cancel</DrawerClose>
    </DrawerFooter>
  </DrawerContent>
</Drawer>
```

### Dropdown Menu

```tsx
<DropdownMenu>
  <DropdownMenuTrigger render={<Button variant="outline" />}>Menu</DropdownMenuTrigger>
  <DropdownMenuContent>
    <DropdownMenuLabel>Actions</DropdownMenuLabel>
    <DropdownMenuSeparator />
    <DropdownMenuGroup>
      <DropdownMenuItem>Profile</DropdownMenuItem>
      <DropdownMenuItem>Settings</DropdownMenuItem>
    </DropdownMenuGroup>
    <DropdownMenuSeparator />
    <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
    <DropdownMenuSeparator />
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>More</DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuItem>Export</DropdownMenuItem>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  </DropdownMenuContent>
</DropdownMenu>
```

Destructive items (`variant="destructive"` on DropdownMenuItem/ContextMenuItem/MenubarItem) render red text on a transparent background, with a red-tinted background only on hover/highlight — they are styled by the menu item itself, not by Button's filled `destructive` variant. Don't pass a Button variant through `render` to restyle a menu item.

Checkbox/radio items:

```tsx
<DropdownMenuCheckboxItem checked={showPanel} onCheckedChange={setShowPanel}>
  Show panel
</DropdownMenuCheckboxItem>

<DropdownMenuRadioGroup value={sort} onValueChange={setSort}>
  <DropdownMenuRadioItem value="name">Name</DropdownMenuRadioItem>
  <DropdownMenuRadioItem value="date">Date</DropdownMenuRadioItem>
</DropdownMenuRadioGroup>
```

### Context Menu (right-click)

Same API as DropdownMenu but with `ContextMenu*` prefix:

```tsx
<ContextMenu>
  <ContextMenuTrigger>Right-click this area</ContextMenuTrigger>
  <ContextMenuContent>
    <ContextMenuItem>Copy</ContextMenuItem>
    <ContextMenuItem>Paste</ContextMenuItem>
    <ContextMenuSeparator />
    <ContextMenuItem variant="destructive">Delete</ContextMenuItem>
  </ContextMenuContent>
</ContextMenu>
```

### Tabs

```tsx
<Tabs defaultValue="tab1">
  <TabsList>
    <TabsTrigger value="tab1">Tab 1</TabsTrigger>
    <TabsTrigger value="tab2">Tab 2</TabsTrigger>
  </TabsList>
  <TabsContent value="tab1">Content 1</TabsContent>
  <TabsContent value="tab2">Content 2</TabsContent>
</Tabs>
```

Line variant: `<TabsList variant="line">`
Vertical: `<Tabs orientation="vertical">`

### Accordion

```tsx
<Accordion type="single" collapsible>
  <AccordionItem value="item-1">
    <AccordionTrigger>Section 1</AccordionTrigger>
    <AccordionContent>Content 1</AccordionContent>
  </AccordionItem>
  <AccordionItem value="item-2">
    <AccordionTrigger>Section 2</AccordionTrigger>
    <AccordionContent>Content 2</AccordionContent>
  </AccordionItem>
</Accordion>
```

### Collapsible

```tsx
<Collapsible>
  <CollapsibleTrigger>Toggle details</CollapsibleTrigger>
  <CollapsibleContent>Hidden content here</CollapsibleContent>
</Collapsible>
```

Icon-only trigger — only the chevron toggles, so the label can be its own button/link and the row can carry trailing content; composes with `variant="folder"` for sidebar trees. Inside `CollapsibleHeader` the trigger overlays the row's start, so give the full-width label button `ps-6` to clear it — hovering anywhere then highlights the whole row while the chevron stays its own click target. An optional `icon` shows at rest and swaps to the chevron when the row is hovered or the trigger focused. The chevron mirrors in RTL; use `ms-auto` (not `ml-auto`) for trailing content. Trigger children become the screen-reader label:

```tsx
<Collapsible variant="folder">
  <CollapsibleHeader>
    <CollapsibleTrigger iconOnly icon={<DatabaseZapIcon />}>
      Toggle sources
    </CollapsibleTrigger>
    <Button variant="default" size="sm" left className="w-full ps-6">
      Sources
      <Text size="xs" variant="muted" render={<span />} className="ms-auto">
        2
      </Text>
    </Button>
  </CollapsibleHeader>
  <CollapsibleContent className="ps-4">{/* rows */}</CollapsibleContent>
</Collapsible>
```

### Popover

```tsx
<Popover>
  <PopoverTrigger render={<Button variant="outline" />}>Open</PopoverTrigger>
  <PopoverContent side="bottom" align="start">
    {/* content */}
  </PopoverContent>
</Popover>
```

`PopoverContent` forwards `collisionAvoidance` to the positioner. Pass `fallbackAxisSide: 'none'` to keep a tall panel on its requested axis (e.g. below the trigger, flipping above only if it won't fit) instead of jumping beside the trigger when vertical space is tight: `collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}`.

### Tooltip

```tsx
<Tooltip>
  <TooltipTrigger render={<Button size="icon" />}>?</TooltipTrigger>
  <TooltipContent side="top">Helpful information</TooltipContent>
</Tooltip>
```

### Radio Group

```tsx
<RadioGroup value={value} onValueChange={setValue}>
  <div className="flex items-center gap-2">
    <RadioGroupItem value="a" id="a" />
    <Label htmlFor="a">Option A</Label>
  </div>
  <div className="flex items-center gap-2">
    <RadioGroupItem value="b" id="b" />
    <Label htmlFor="b">Option B</Label>
  </div>
</RadioGroup>
```

### Button Group

```tsx
<ButtonGroup>
  <Button>Left</Button>
  <ButtonGroupSeparator />
  <Button>Right</Button>
</ButtonGroup>
```

Vertical: `<ButtonGroup orientation="vertical">`

### Empty State

```tsx
<Empty>
  <EmptyHeader>
    <EmptyMedia variant="icon">
      <InboxIcon />
    </EmptyMedia>
    <EmptyTitle>No items</EmptyTitle>
    <EmptyDescription>Get started by creating your first item.</EmptyDescription>
  </EmptyHeader>
  <EmptyContent>
    <Button>Create item</Button>
  </EmptyContent>
</Empty>
```

### Item List

```tsx
<ItemGroup>
  <Item variant="pressable">
    <ItemMedia variant="icon">
      <UserIcon />
    </ItemMedia>
    <ItemContent>
      <ItemTitle>John Doe</ItemTitle>
      <ItemDescription>john@example.com</ItemDescription>
    </ItemContent>
    <ItemActions>
      <Button variant="outline" size="icon-xs">
        <MoreIcon />
      </Button>
    </ItemActions>
  </Item>
  <ItemSeparator />
  <Item variant="pressable">
    <ItemMedia variant="icon">
      <UserIcon />
    </ItemMedia>
    <ItemContent>
      <ItemTitle>Jane Smith</ItemTitle>
      <ItemDescription>jane@example.com</ItemDescription>
    </ItemContent>
  </Item>
</ItemGroup>
```

Item variants: default, outline, pressable, muted, menuItem
Item sizes: default, sm, xs
`<ItemGroup>` spaces items with a gap by default; pass `combined` to merge them into one flush list (no gap, squared interior corners, collapsed shared borders, rounded outer corners — like CardGroup)
Item tones (the `tone` prop — named `tone`, not `color`, to avoid colliding with the DOM `color` attribute when Base UI render props are spread onto ItemCheckbox/ItemRadio): default, info, success, warning, completed, destructive — a semantic tint orthogonal to `variant`, designed to pair with `variant="pressable"` for colored clickable rows (e.g. `<Item variant="pressable" tone="success" render={<a href="…" />}>`)

### Avatar

Compose `Avatar > AvatarImage + AvatarFallback`. The fallback (initials or a bare lucide icon — don't `size-*` it) shows when there's no image or the image errors. `size="xs"` (1.25rem), `"sm"` (1.5rem), default (2rem), or `"lg"` (2.35rem). For a clickable profile avatar, pass `render={<a href="…" />}` (or `<button />`) — the avatar renders as that element and gains pointer + focus ring; the `AvatarImage` `alt` becomes the link's accessible name, so keep it meaningful.

```tsx
<Avatar>
  <AvatarImage src={user.avatarUrl} alt={user.name} />
  <AvatarFallback>{initials}</AvatarFallback>
</Avatar>
```

`AvatarGroup` lays Avatars out in a row — gapped by default, or `stacked` to overlap them. The leftmost avatar sits on top (so a leading `+N` count reads in front). Hovering (or focusing) a stacked group spreads it back to the inline gap; the spread is a `transform`, so the container box never changes and nothing reflows — the avatars slide out over the space beside them. `reverse` mirrors it: the pile anchors to its right edge, the rightmost avatar sits on top, and it spreads left (use it at the right end of a row so it grows inward). `size` on the group forwards to bare Avatar children and tunes the overlap; a non-Avatar child (a `+N` count built from a styled `AvatarFallback`) passes through untouched — put it first (default) or last (`reverse`) so it sits on top. The stacked ring defaults to the app background; on a different surface (a `Card`), override `--quill-avatar-ring` so it matches, e.g. `className="[--quill-avatar-ring:var(--card)]"`.

```tsx
<AvatarGroup stacked size="sm">
  {members.map((m) => (
    <Avatar key={m.id}>
      <AvatarImage src={m.avatarUrl} alt={m.name} />
      <AvatarFallback>{m.initials}</AvatarFallback>
    </Avatar>
  ))}
</AvatarGroup>
```

### Thread item (chat feed row)

A feed-style message row — Slack-like channel surfaces where every message aligns start. Use `ChatBubble`/`ChatMessage` for conversational back-and-forth instead. The row highlights on hover/focus-within and reveals `ThreadItemActions` (a `role="toolbar"`, hidden with opacity so its buttons stay tabbable). The toolbar is a Base UI Toolbar — one tab stop, arrow keys rove between actions. Fill it with `ThreadItemAction` — a Button wrapped in a Tooltip where `label` is both the `aria-label` and the tooltip content (one source of truth); it forwards all Button props including `render` (`render={<a href="…" />}` for a link action) and forwards its ref, so it also works as a render target (`DropdownMenuTrigger render={<ThreadItemAction …/>}`). `ThreadItemActions` carries its own `TooltipProvider`, so the tooltips work without app-root setup; a `ThreadItemAction` used outside the toolbar (e.g. an add-reaction button in `ThreadItemReactions`) needs a `TooltipProvider` ancestor. Don't hand-roll `Tooltip > Button` pairs inside the toolbar. `ThreadItemReaction` is a Base UI Toggle (`pressed`/`onPressedChange`); give it an `aria-label` with the emoji name + count and wrap the glyph in `ThreadItemReactionEmoji` (aria-hidden). `ThreadItemAuthor` and `ThreadItemReplies` accept `render` (author as profile link/button via `render={<a href="…" />}` — it keeps the foreground name color with underline on hover, never link-tinted; replies as link); `ThreadItemReplies` is a Button (variant `default`) stretched to the content column. On continuation rows (same author), drop the header and put a `ThreadItemTimestamp` in the gutter — it shows only while the row is hovered/focused — and start the body with an `sr-only` author span so screen readers still hear who is speaking.

`ThreadItemHeader` is an open flex row — put author meta (a `Badge`, a bot tag) between the author and timestamp. Inside `ThreadItemBody`, use `ThreadItemMention` for @mentions (a tinted pill; `render={<button />}` to open a profile) and `ThreadItemLink` for inline links. For image/file previews, use `ThreadItemAttachment` (a Base UI Collapsible, open by default) > `ThreadItemAttachmentTrigger` (the filename + rotating chevron, `aria-expanded` built in) + `ThreadItemAttachmentContent` > `ThreadItemAttachmentImage` (framed `img` — `alt` is required by the type).

```tsx
<ThreadItemBody>
  <ThreadItemMention render={<button type="button" />}>@Adam L</ThreadItemMention> why this checkbox? See{' '}
  <ThreadItemLink href="/docs">the docs</ThreadItemLink>.
</ThreadItemBody>
<ThreadItemAttachment>
  <ThreadItemAttachmentTrigger>image.png</ThreadItemAttachmentTrigger>
  <ThreadItemAttachmentContent>
    <ThreadItemAttachmentImage src={url} alt="Screenshot of the setting" />
  </ThreadItemAttachmentContent>
</ThreadItemAttachment>
```

```tsx
<ThreadItemGroup>
  <ThreadItem>
    <ThreadItemGutter>
      <Avatar>…</Avatar>
    </ThreadItemGutter>
    <ThreadItemContent>
      <ThreadItemHeader>
        <ThreadItemAuthor>Adam L</ThreadItemAuthor>
        <ThreadItemTimestamp dateTime="2026-07-01T16:23:00">4:23 PM</ThreadItemTimestamp>
      </ThreadItemHeader>
      <ThreadItemBody>Message text…</ThreadItemBody>
      <ThreadItemReactions>
        <ThreadItemReaction pressed={pressed} onPressedChange={setPressed} aria-label="Victory hand, 1 reaction">
          <ThreadItemReactionEmoji>✌️</ThreadItemReactionEmoji>1
        </ThreadItemReaction>
        <ThreadItemAction label="Add reaction" className="rounded-full">
          <SmilePlusIcon />
        </ThreadItemAction>
      </ThreadItemReactions>
      <ThreadItemReplies onClick={openThread}>
        <AvatarGroup size="xs">…</AvatarGroup>
        <ThreadItemRepliesLabel>1 reply</ThreadItemRepliesLabel>
        <ThreadItemRepliesMeta>Today at 4:40 PM</ThreadItemRepliesMeta>
      </ThreadItemReplies>
    </ThreadItemContent>
    <ThreadItemActions>
      <ThreadItemAction label="Add reaction">
        <SmilePlusIcon />
      </ThreadItemAction>
      <ThreadItemAction label="More actions">
        <EllipsisVerticalIcon />
      </ThreadItemAction>
    </ThreadItemActions>
  </ThreadItem>
</ThreadItemGroup>
```

### Keyboard Shortcuts

```tsx
<KbdGroup>
  <Kbd>Cmd</Kbd>
  <KbdText>+</KbdText>
  <Kbd>K</Kbd>
</KbdGroup>
```

### Resizable Panels

```tsx
<ResizablePanelGroup direction="horizontal">
  <ResizablePanel defaultSize={50}>Left panel</ResizablePanel>
  <ResizableHandle withHandle />
  <ResizablePanel defaultSize={50}>Right panel</ResizablePanel>
</ResizablePanelGroup>
```

### Scroll Area

```tsx
<ScrollArea className="h-72">
  {/* long content */}
  <ScrollBar orientation="vertical" />
</ScrollArea>
```

Disable scroll shadows: `<ScrollArea scrollShadows={false}>`

### Pagination

Presentational, stateless parts — you own the page state. `getPaginationRange(pageCount, pageIndex)` returns 0-based page indices and `'ellipsis'` tokens (first/last + a sibling window) for large counts.

```tsx
const range = getPaginationRange(pageCount, pageIndex)
;<Pagination>
  <PaginationContent>
    <PaginationItem>
      <PaginationPrevious disabled={pageIndex === 0} onClick={() => setPage(pageIndex - 1)} />
    </PaginationItem>
    {range.map((item, i) =>
      item === 'ellipsis' ? (
        <PaginationItem key={`e-${i}`}>
          <PaginationEllipsis />
        </PaginationItem>
      ) : (
        <PaginationItem key={item}>
          <PaginationButton isActive={item === pageIndex} onClick={() => setPage(item)}>
            {item + 1}
          </PaginationButton>
        </PaginationItem>
      )
    )}
    <PaginationItem>
      <PaginationNext disabled={pageIndex === pageCount - 1} onClick={() => setPage(pageIndex + 1)} />
    </PaginationItem>
  </PaginationContent>
</Pagination>
```

`DataTable` (quill-components) wires this onto TanStack pagination — pass `pageSize` to opt in.

### Table

Compose `Table > TableHeader/TableBody/TableFooter > TableRow > TableHead/TableCell`. Per-cell options on `TableHead`/`TableCell`: `sticky="left" | "right"` (frozen column), `align="left" | "center" | "right"` (horizontal), `valign="top" | "middle" | "bottom"` (vertical), `expand` (absorb leftover width). `align` also positions an inline-flex header Button. On `Table`: `stickyHeader` (or `"page"`) for a sticky header, `fullWidth` to fill the container — pair `fullWidth` with `expand` on one column to choose which one stretches, `size="sm"` to tighten head/cell inline padding to `0.75rem` (from `1rem`) for dense tables and to align edge columns with a `Card size="sm"`.

**Backgrounds: transparent by default, opaque when sticky.** Plain cells and headers are transparent, so a `Table` inherits whatever surface it sits on (inside a `Card`, a tinted panel). Sticky parts (`stickyHeader`, `stickyHeader="page"`, `sticky="left"/"right"`) get an opaque background automatically — they'd otherwise bleed scrolled-under content — so you don't add `bg-background` yourself. It defaults to the app background; if the table sits on a different surface, override the inherited `--quill-table-sticky-bg` custom property on the `Table` so the frozen cells match — e.g. inside a `Card`, `className="[--quill-table-sticky-bg:var(--card)]"`.

**Empty state — use `TableEmpty`, not a hand-rolled cell.** Drop `TableEmpty` in where a `TableBody` would go; it renders its own `tbody > tr > td` with a full-span `colSpan` (defaults huge, browsers clamp to the real column count) and centers its content. Put `<Empty>` or plain text inside — no manual `colSpan`, no `h-full`. To make it fill the body area, give the `Table` a height (e.g. `className="h-full"` with a height-bounded container); otherwise it sizes to its content. Don't put an `<Empty>` (a `div`) as a direct child of `Table` — that's invalid table markup and the browser hoists it out of the grid.

```tsx
<Table fullWidth className="h-full">
  <TableHeader>{/* … */}</TableHeader>
  <TableEmpty>
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <InboxIcon />
        </EmptyMedia>
        <EmptyTitle>No members yet</EmptyTitle>
        <EmptyDescription>Invite teammates to start collaborating.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button>Invite member</Button>
      </EmptyContent>
    </Empty>
  </TableEmpty>
</Table>
```

**Table in a Card — let the table own the edges.** A `Table` sits flush inside a `Card` because its cells are transparent (they inherit the card surface). Pass `flush` on the `Card` so the table reaches the card's rounded edges with no double padding (it drops the card's section gap + bottom padding and the `CardContent`'s inline padding — no `className` needed on either), and use `fullWidth` on the `Table`. For an empty/loading table that should fill a tall card, build the height chain `Card min-h-* → CardContent flex-1 → Table h-full` so `TableEmpty` stretches to the body area. Inside a `Card size="sm"`, also pass `size="sm"` on the `Table` so its edge columns line up with the card's tighter `0.75rem` inline padding (header title, footer).

```tsx
<Card size="sm" flush>
  <CardHeader>
    <CardTitle>Members</CardTitle>
  </CardHeader>
  <CardContent>
    <Table size="sm" fullWidth>
      {/* … */}
    </Table>
  </CardContent>
</Card>
```

### Menubar

```tsx
<Menubar>
  <MenubarMenu>
    <MenubarTrigger>File</MenubarTrigger>
    <MenubarContent>
      <MenubarItem>
        New Tab <MenubarShortcut>Cmd+T</MenubarShortcut>
      </MenubarItem>
      <MenubarSeparator />
      <MenubarSub>
        <MenubarSubTrigger>Share</MenubarSubTrigger>
        <MenubarSubContent>
          <MenubarItem>Email</MenubarItem>
        </MenubarSubContent>
      </MenubarSub>
    </MenubarContent>
  </MenubarMenu>
</Menubar>
```

MenubarItem wraps DropdownMenuItem, so the same item API applies — including `variant="destructive"` (red text, red-tinted highlight, transparent at rest).

### Toast

Add `<ToastProvider />` once at app root (see Setup), then call `toast` with an options object — not a string:

```tsx
import { toast } from '@posthog/quill-primitives'

toast({ title: 'Hello world' })
toast.success({ title: 'Saved successfully' })
toast.error({ title: 'Something went wrong', description: 'Try again later' })

// Loading → resolve by id
const id = toast.loading({ title: 'Processing...' })
toast.update(id, { type: 'success', title: 'Done' })
toast.dismiss(id)

// With an action button
toast({ title: 'Item archived', action: { label: 'Undo', onClick: () => restore() } })
```

### Theme Toggle

```tsx
import { useTheme } from '@posthog/quill-primitives'

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  return (
    <Button variant="outline" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
      {theme === 'dark' ? 'Light' : 'Dark'}
    </Button>
  )
}
```

Note: pressing `d` also toggles theme (skipped when focus is in input fields).

---

## Spacing and layout

Quill spacing uses a 4px base (`gap-1` = 4px, `gap-2` = 8px, `gap-4` = 16px). These rules are the conventions the stories actually follow:

### Between siblings — use gap, never margins

- `gap-2` — the default between related sibling controls, in rows and stacks: button rows, checkbox + label, icon + text. When unsure, use `gap-2`.
- `gap-1` — tight pairs only: a label and its inline meta/hint.
- `gap-4` — between sections: stacked form fields (FieldGroup's built-in default), dialog body sections, page regions.
- `gap-px` — packed menu-like lists on a `bg-muted` surface (1px visual seams).
- `gap-0` / `<ItemGroup combined>` / `<CardGroup>` — merged lists and stacked cards with shared borders.

Don't space siblings with `mt-*`/`mb-*` — put `flex flex-col gap-*` (or `flex gap-*`) on the parent.

### Don't re-pad primitive internals

Primitives carry their own padding and heights. Adding `p-*`/`h-*` via `className` on top of them fights the system:

| Primitive                          | Built-in                                                                              |
| ---------------------------------- | ------------------------------------------------------------------------------------- |
| Button                             | h-7 px-2 (default), h-6 (sm), h-5 (xs), h-8 (lg); gap-2 icon spacing                  |
| Input                              | h-8, px-2                                                                             |
| Card / CardHeader / CardContent    | 1rem block + inline padding, gap-4 between sections (0.75rem / gap-3 for `size="sm"`) |
| Menu popups (Dropdown/Context/...) | p-1 scroller; items pad themselves                                                    |
| Item                               | py-2.5 px-3 (default/sm), py-2 px-2.5 (xs)                                            |
| Field / FieldGroup                 | gap-y-1 within a field, gap-4 between fields                                          |

Sanctioned escape hatches (the only padding overrides the stories use):

- `p-0` on `DialogContent` when an inner component (e.g. a Combobox list) should consume the full dialog.
- `p-0` on `Item size="xs"` in dense nested contexts (inside table cells, combobox rows).
- `ml-auto` to push an element to the end of a flex row (alignment, not spacing).

### Width and containers

- Constrain single-column forms and lists: `w-full max-w-sm` is the standard.
- Fixed sidebars/navs: explicit width (`w-[200px]`-ish), content area `flex-1`.
- `flex flex-col` is the default layout; reach for `grid` only for genuinely two-dimensional layouts.
- Tailwind utilities only — no inline styles; semantic tokens (`bg-muted`, `text-muted-foreground`) — never raw colors.

---

## Icons

Primitives size and lay out their own icons — drop a bare lucide icon in as a child and it just works:

```tsx
<Button>
  <Copy />
  Copy
</Button>
```

Each container's CSS handles `flex-shrink: 0` and the per-context size via `svg:not([class*='size-'])` selectors (or the `[&_svg:not([class*="size-"])]:size-*` Tailwind equivalent):

| Context                               | Icon size           |
| ------------------------------------- | ------------------- |
| Button                                | 1rem (size-4)       |
| Menu items (Dropdown/Context/Menubar) | 0.875rem (size-3.5) |
| TabsTrigger                           | 0.75rem (size-3)    |

**Don't add `size-*` classes to icons inside primitives.** The `:not([class*='size-'])` guard means an explicit `size-*` class is treated as a deliberate override and the component's sizing steps aside — so reserve it for the rare case where you genuinely need a different size. Color also inherits (`currentColor`), so don't set icon colors either; variants tint their icons themselves.

---

## Rules

1. **Use Field for forms** — don't compose raw Label + Input, use Field > FieldLabel + Input + FieldDescription/FieldError
2. **Wrap app with providers** — ThemeProvider at root, TooltipProvider if using tooltips, ToastProvider if using toasts
3. **Badge variants are semantic** — info (blue), warning (yellow), success (green), completed (purple, terminal done state e.g. merged PRs), destructive (red), default (neutral)
4. **Use `render` on triggers** — DialogTrigger, PopoverTrigger, TooltipTrigger, DrawerTrigger accept `render` to render as the child element
5. **DropdownMenuItem has variants** — use `variant="destructive"` for dangerous actions; default is `"default"`
6. **Prefer composition over props** — use CardHeader > CardTitle instead of `<Card title="...">`
7. **Use `cn()` for class overrides** — import from `@posthog/quill-primitives` to merge Tailwind classes safely
8. **Follow the spacing conventions** — see Spacing and layout above; `gap-2` between related siblings, `gap-4` between sections, never re-pad primitive internals
9. **Use `loading` on submit buttons** — any Button that triggers a network request must pass `loading` while the request is in flight; it blocks activation (guarding double-submission) and overlays a spinner without changing the button's width, while staying focusable for screen readers (`aria-disabled` + `aria-busy`, not the native `disabled` attribute)
10. **Don't size or color icons inside primitives** — see Icons above; component CSS sizes bare svg children per context, and `currentColor` handles tinting
