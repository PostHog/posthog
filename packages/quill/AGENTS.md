# Quill Primitives — Agent Guide

## What is Quill?

Quill is PostHog's design system built on React, TypeScript, Base UI, and Tailwind v4.
It follows a layered architecture: **tokens > primitives > components > blocks**.

This guide covers the **primitives** layer — the foundational UI components that everything else builds on.

## Package structure

```text
packages/quill/
├── packages/
│   ├── tokens/       @posthog/quill-tokens      — Design tokens (JS + generated CSS)
│   ├── primitives/   @posthog/quill-primitives   — Base UI components (this guide)
│   ├── components/   @posthog/quill-components   — Composed primitives
│   └── blocks/       @posthog/quill-blocks       — Product-level patterns
└── apps/
    └── storybook/    — Component documentation
```

## Core patterns

### 1. Base UI wrapping

Every interactive primitive wraps a `@base-ui/react` component.
Base UI provides behavior, accessibility, and state — we add styling via Tailwind.

```tsx
import { Button as ButtonPrimitive } from '@base-ui/react/button'

const Button = React.forwardRef<HTMLButtonElement, Props>(({ className, variant, size, ...props }, ref) => (
  <ButtonPrimitive
    ref={ref}
    data-slot="button"
    className={cn(buttonVariants({ variant, size }), className)}
    {...props}
  />
))
```

### 2. CVA for variants

All variant styling uses `class-variance-authority`.
Define variants as a `cva()` call, export the variants type for consumers.

```tsx
import { cva, type VariantProps } from 'class-variance-authority'

const buttonVariants = cva('inline-flex items-center ...', {
  variants: {
    variant: {
      default: 'bg-secondary ...',
      outline: 'border-foreground/10 ...',
      ghost: 'hover:bg-accent/40 ...',
    },
    size: {
      default: 'h-7 px-2 text-xs',
      sm: 'h-6 px-2 text-xs',
      xs: 'h-5 px-2 text-[0.625rem]',
    },
  },
  defaultVariants: { variant: 'default', size: 'default' },
})
```

### 3. `cn()` utility

Always use `cn()` from `./lib/utils` for class merging.
It combines `clsx` (conditional classes) + `tailwind-merge` (conflict resolution).

```tsx
import { cn } from './lib/utils'
className={cn(baseClasses, conditional && 'extra-class', className)}
```

### 4. `data-slot` attributes

Every component root sets `data-slot="component-name"`.
This enables parent-based styling via `has-data-[slot=...]` and `*:data-[slot=...]`.

### 5. `forwardRef` for render prop targets

Any component used as a `render={<Component />}` target in Base UI **must** use `React.forwardRef`.
React 18 does not forward refs to function components — Base UI's render prop passes refs.

Components that need `forwardRef`:

- `Button`, `Input`, `Chip`, `ChipClose`
- `InputGroup`, `InputGroupInput`, `InputGroupButton`
- `ComboboxTrigger`
- Any component passed to Base UI's `render` prop

### 6. Composition hierarchy

```text
Button
├── Chip (default size=sm, variant=outline)
├── ChipClose (variant=ghost, size=icon-xs)
├── InputGroupButton
├── TabsTrigger (render prop)
├── CollapsibleTrigger (render prop)
├── SelectTrigger (render prop)
├── DropdownMenuItem (render prop)
└── ToggleGroupItem (render prop)

Input
└── InputGroupInput (border-0, bg-transparent)

InputGroup
├── ComboboxInput (with anchor context)
└── CommandInput

Chip + ChipClose
└── ComboboxChip (via render prop)

ButtonGroup
└── ChipGroup (flex-wrap, gap-0)
```

## Component conventions

### Creating a new primitive

1. Wrap the Base UI component
2. Add `data-slot="your-component"` to the root
3. Use `forwardRef` if the component may be used in `render` props
4. Define variants with CVA if the component has visual variants
5. Accept `className` prop and merge with `cn()`
6. Export from the component file (barrel export is in `index.ts`)

### Styling rules

- Use Tailwind utility classes exclusively — no inline styles, no CSS modules
- Use semantic color tokens: `bg-primary`, `text-foreground`, `border-input` — never raw colors
- Use `group/name` for scoped parent selectors (e.g., `group/tabs`, `group/input-group`)
- Use `data-[variant=...]` selectors for variant-aware child styling
- Focus states: `focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30`
- Invalid states: `aria-invalid:bg-destructive/50 aria-invalid:border-destructive-foreground/30`
- Disabled states: `disabled:pointer-events-none disabled:opacity-50`
- Dark mode: use `dark:` prefix only when light/dark need different values beyond token swapping

### Base UI render prop pattern

When composing primitives inside Base UI components, use the `render` prop:

```tsx
// Good — Base UI manages behavior, our component provides styling
<ComboboxPrimitive.Chip render={<Chip />}>
    {children}
</ComboboxPrimitive.Chip>

// Good — nesting render props
<InputGroupButton render={<ComboboxTrigger />} />
```

### Context for cross-sibling communication

When siblings need shared state (e.g., `ComboboxInput` and `ComboboxContent` sharing an anchor ref),
use React context at their common parent:

```tsx
const AnchorContext = React.createContext<React.RefObject<HTMLDivElement> | null>(null)

function Parent({ children }) {
  const ref = React.useRef<HTMLDivElement>(null!)
  return (
    <AnchorContext.Provider value={ref}>
      <Primitive.Root>{children}</Primitive.Root>
    </AnchorContext.Provider>
  )
}
```

## Storybook

- Stories live next to components: `component.stories.tsx`
- Use `Meta<typeof Component>` type annotation (not `satisfies Meta<typeof Component>` — avoids strict args issues with Base UI props)
- Each story should demonstrate a distinct use case
- Run storybook: `pnpm --filter storybook dev`

## Commands

- Dev storybook: `pnpm --filter storybook dev`
- Build primitives: `pnpm --filter @posthog/quill-primitives build`
- Build tokens: `pnpm --filter @posthog/quill-tokens build`
- Format: use prettier via the quill root config

## Key dependencies

| Package                    | Purpose                                           |
| -------------------------- | ------------------------------------------------- |
| `@base-ui/react`           | Headless UI primitives (behavior + accessibility) |
| `class-variance-authority` | Type-safe variant class maps                      |
| `clsx` + `tailwind-merge`  | Class merging without conflicts                   |
| `lucide-react`             | Icons                                             |
| `vaul`                     | Drawer primitive                                  |
| `react-resizable-panels`   | Resizable panel layout                            |
| `cmdk`                     | Command palette                                   |
| `sonner`                   | Toast notifications                               |

## Token system

Components never import color values directly.
They use Tailwind classes (`bg-primary`, `text-foreground`) which reference CSS custom properties (`--primary`, `--foreground`).

The token flow:

1. `@posthog/quill-tokens` defines colors as JS objects
2. Build script generates `color-system.css` (actual values) and `styles.css` (`@theme` mappings)
3. Primitives ship only the `@theme` mappings — the consuming app provides `color-system.css`

This means primitives are theme-agnostic — swap `color-system.css` for a different theme.
