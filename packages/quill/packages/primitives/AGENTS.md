# Primitives — Agent Reference

Quick-reference for AI agents using `@posthog/quill-primitives`. Show composition, not API docs.

## Setup

```tsx
import { ThemeProvider, TooltipProvider } from '@posthog/quill-primitives'

function App() {
  return (
    <ThemeProvider defaultTheme="system">
      <TooltipProvider>
        <YourApp />
      </TooltipProvider>
    </ThemeProvider>
  )
}
```

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

## Component Catalog

| Component    | Variants                                               | Sizes                                                | Notes                            |
| ------------ | ------------------------------------------------------ | ---------------------------------------------------- | -------------------------------- |
| Button       | default, outline, ghost, destructive, link, link-muted | default, xs, sm, lg, icon, icon-xs, icon-sm, icon-lg |                                  |
| Badge        | default, info, destructive, warning, success           | —                                                    | Semantic status                  |
| Toggle       | default, outline                                       | default, sm, lg, icon                                |                                  |
| Chip         | outline                                                | sm                                                   | Use with ChipClose               |
| Separator    | —                                                      | —                                                    | orientation: horizontal/vertical |
| Spinner      | —                                                      | —                                                    | SVG, accepts svg props           |
| Skeleton     | —                                                      | —                                                    | Pulsing placeholder div          |
| SkeletonText | —                                                      | —                                                    | lines, minWidth, maxWidth        |
| Progress     | —                                                      | —                                                    | value: 0-100                     |
| Slider       | —                                                      | —                                                    | value, min, max                  |

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

### Popover

```tsx
<Popover>
  <PopoverTrigger render={<Button variant="outline" />}>Open</PopoverTrigger>
  <PopoverContent side="bottom" align="start">
    {/* content */}
  </PopoverContent>
</Popover>
```

### Tooltip

```tsx
<Tooltip>
  <TooltipTrigger render={<Button size="icon" />}>?</TooltipTrigger>
  <TooltipContent side="top">Helpful information</TooltipContent>
</Tooltip>
```

### Command Palette

```tsx
<Command>
  <CommandInput placeholder="Search commands..." />
  <CommandList>
    <CommandEmpty>No results found.</CommandEmpty>
    <CommandGroup heading="Actions">
      <CommandItem>
        New file
        <CommandShortcut>Cmd+N</CommandShortcut>
      </CommandItem>
      <CommandItem>Search</CommandItem>
    </CommandGroup>
    <CommandSeparator />
    <CommandGroup heading="Settings">
      <CommandItem>Preferences</CommandItem>
    </CommandGroup>
  </CommandList>
</Command>
```

As a dialog:

```tsx
<CommandDialog open={open} onOpenChange={setOpen}>
  <CommandInput placeholder="Type a command..." />
  <CommandList>
    <CommandItem>...</CommandItem>
  </CommandList>
</CommandDialog>
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
      <Button variant="ghost" size="icon-xs">
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

### Toast (Sonner)

Add `<Toaster />` once at app root, then use sonner's `toast()`:

```tsx
import { Toaster } from '@posthog/quill-primitives'
import { toast } from 'sonner'

// In app root:
;<Toaster />

// Anywhere:
toast.success('Saved successfully')
toast.error('Something went wrong')
toast('Hello world')
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

## Rules

1. **Use Field for forms** — don't compose raw Label + Input, use Field > FieldLabel + Input + FieldDescription/FieldError
2. **Wrap app with providers** — ThemeProvider at root, TooltipProvider if using tooltips, Toaster if using toasts
3. **Badge variants are semantic** — info (blue), warning (yellow), success (green), destructive (red), default (neutral)
4. **Use `render` on triggers** — DialogTrigger, PopoverTrigger, TooltipTrigger, DrawerTrigger accept `render` to render as the child element
5. **DropdownMenuItem has variants** — use `variant="destructive"` for dangerous actions, default is `"ghost"`
6. **Prefer composition over props** — use CardHeader > CardTitle instead of `<Card title="...">`
7. **Use `cn()` for class overrides** — import from `@posthog/quill-primitives` to merge Tailwind classes safely
8. **Quill spacing uses 4px base** — spacing-1 = 4px, spacing-2 = 8px, spacing-3 = 12px, spacing-4 = 16px
