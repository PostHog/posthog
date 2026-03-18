# PostHog Design System

Extracted from codebase. Source of truth for UI consistency.

## Spacing

- **Base unit**: 4px (0.25rem)
- **Scale**: 4, 8, 12, 16, 24, 32
- **Default gap**: 8px (`gap-2`) — used in 55% of layouts
- **Default padding**: 8px (`p-2`) or 16px (`p-4`)
- **Scene padding**: `var(--scene-padding)`

## Border Radius

| Token         | Value           | Usage                              |
| ------------- | --------------- | ---------------------------------- |
| `--radius-sm` | 4px (0.25rem)   | Small elements, tags               |
| `--radius`    | 6px (0.375rem)  | Default — buttons, inputs, cards   |
| `--radius-lg` | 10px (0.625rem) | Popovers, menus, larger containers |
| `full`        | 9999px          | Avatars, pills, circular elements  |

Prefer `rounded` (default) for most elements. Use `rounded-lg` for popovers and elevated containers.

## Depth Strategy

**Borders-first.** Shadows are rare and intentional.

- **Primary border**: `var(--color-border-primary)` — posthog-3000 warm gray
- **Secondary border**: `var(--color-border-secondary)` — darker variant
- **Semantic borders**: `--color-border-info`, `--color-border-warning`, `--color-border-error`, `--color-border-success`
- **Default shadow**: `var(--shadow-elevation-3000)` = `0 3px 0 <border-color>` — only for elevated cards and toasts
- **Modal shadow**: `var(--modal-shadow-elevation)` = `0px 16px 16px -16px rgb(0 0 0 / 35%)`

Do not add shadows for general UI. Reserve for modals, dropdowns, and hover-elevated cards.

## Colors

### Accent

| Token                     | Light                     | Dark                     |
| ------------------------- | ------------------------- | ------------------------ |
| `--color-accent`          | HSL(19, 100%, 48%) orange | HSL(43, 94%, 57%) yellow |
| `--color-accent-hover`    | +10% lightness            | +10% lightness           |
| `--color-accent-active`   | +15% lightness            | +15% lightness           |
| `--color-accent-inverted` | Yellow                    | Orange                   |

### Backgrounds

| Token                  | Light            | Dark             |
| ---------------------- | ---------------- | ---------------- |
| `bg-primary`           | posthog-3000-50  | neutral-cool-950 |
| `bg-surface-primary`   | white            | neutral-cool-850 |
| `bg-surface-secondary` | posthog-3000-100 | neutral-cool-900 |
| `bg-surface-tertiary`  | posthog-3000-150 | neutral-cool-950 |
| `bg-fill-primary`      | white            | neutral-cool-900 |
| `bg-fill-secondary`    | posthog-3000-25  | neutral-cool-850 |
| `bg-fill-tertiary`     | posthog-3000-50  | neutral-cool-800 |

### Highlight fills (opacity-based)

Use `bg-fill-highlight-{50,100,150,200}` for subtle black overlays (light mode) or white overlays (dark mode). These use `color-mix()` for transparency.

### Text

| Token            | Light       | Dark        |
| ---------------- | ----------- | ----------- |
| `text-primary`   | neutral-950 | neutral-100 |
| `text-secondary` | neutral-750 | neutral-350 |
| `text-tertiary`  | neutral-600 | neutral-400 |
| `text-success`   | green-600   | green-400   |
| `text-warning`   | yellow-700  | yellow-400  |
| `text-error`     | red-600     | red-400     |

### Semantic

| Token     | Value   |
| --------- | ------- |
| `danger`  | #db3707 |
| `warning` | #f7a501 |
| `success` | #388600 |

### Data colors

15 series colors (`--data-color-1` through `--data-color-15`) for charts. Some override in dark mode. Always use hex for Chart.js compatibility.

### Brand

| Token            | Value                      |
| ---------------- | -------------------------- |
| `--brand-blue`   | #1d4aff                    |
| `--brand-red`    | #f54e00                    |
| `--brand-yellow` | #f9bd2b                    |
| `--brand-key`    | #000 (light) / #fff (dark) |

## Typography

| Property      | Value                                             |
| ------------- | ------------------------------------------------- |
| Base size     | 14px                                              |
| Line height   | 1.5715                                            |
| Font sans     | -apple-system, BlinkMacSystemFont, Inter, ...     |
| Font title    | MatterSQ, -apple-system, Inter, ...               |
| Font mono     | ui-monospace, SFMono-Regular, SF Mono, Menlo, ... |
| Font medium   | 500                                               |
| Font semibold | 600                                               |

### Headings

| Level | Size      | Weight | Font                                          |
| ----- | --------- | ------ | --------------------------------------------- |
| h1    | 1.75rem   | 500    | font-title                                    |
| h2    | 1.3125rem | 500    | font-title                                    |
| h3    | 1rem      | 500    | font-title                                    |
| h5    | 0.6875rem | 600    | font-title, uppercase, letter-spacing 0.075em |

## Component Patterns

### Button (LemonButton)

| Size    | Height | H-Padding | V-Padding | Font Size |
| ------- | ------ | --------- | --------- | --------- |
| xxsmall | 20px   | 4px       | 2px       | 0.6875rem |
| xsmall  | 26px   | 6px       | 4px       | 0.75rem   |
| small   | 33px   | 8px       | 8px       | inherit   |
| medium  | 37px   | 12px      | 4px       | 0.875rem  |
| large   | 49px   | 12px      | 12px      | 1rem      |

- Border radius: `var(--radius)` (6px)
- Default size: medium

### Input (LemonInput)

| Size   | Height | H-Padding | V-Padding |
| ------ | ------ | --------- | --------- |
| xsmall | 24px   | 4px       | 2px       |
| small  | 32px   | 4px       | 2px       |
| medium | 37px   | 8px       | 4px       |
| large  | 48px   | —         | —         |

- Border: `1px solid var(--color-border-primary)`
- Border radius: `var(--radius)` (6px)
- Focus ring: `box-shadow: 0 0 0 3px var(--color-bg-fill-highlight-75)`

### Card (LemonCard)

- Border: `1px solid` (default border color)
- Padding: 24px (`p-6`)
- Border radius: `var(--radius)` (6px)
- Background: `bg-surface-primary`
- Hover (when hoverEffect): `box-shadow: var(--shadow-elevation-3000)` + `scale(1.01)`

### Modal (LemonModal)

- Border: `1px solid var(--border-bold)`
- Border radius: `var(--radius)` (6px)
- Shadow: `var(--modal-shadow-elevation)`
- Header/Content/Footer padding: 16px (`1rem`)
- Backdrop: `rgb(0 0 0 / 20%)`, blur `5px`
- Transition: 200ms

### Popover / Menu

- Background: `bg-surface-primary`
- Border: `1px solid var(--color-border-primary)`
- Border radius: `var(--radius-lg)` (10px)
- Shadow: `var(--shadow-elevation-3000)`
- Min width: 8rem
- Max width: 200px

### Toast

- Padding: 12px (`0.75rem`)
- Border: `1px solid var(--secondary-3000-button-border)`
- Border radius: `var(--radius)` (6px)
- Shadow: `var(--shadow-elevation-3000)`
- Font: 0.875rem, weight 500

## Layout

| Token                              | Value |
| ---------------------------------- | ----- |
| `--project-navbar-width`           | 215px |
| `--project-navbar-width-collapsed` | 45px  |
| `--project-panel-width`            | 245px |
| `--side-panel-bar-width`           | 40px  |

### Breakpoints

| Token | Value  |
| ----- | ------ |
| sm    | 576px  |
| md    | 768px  |
| lg    | 992px  |
| xl    | 1200px |
| 2xl   | 1600px |

## Dark Mode

- Selector: `[theme="dark"]` on body
- Tailwind: `darkMode: ['selector', '[theme="dark"]']`
- Accent swaps: orange (light) / yellow (dark)
- Surfaces swap to neutral-cool 800-950 range
- Borders swap to neutral-cool 600-800

## Z-Index Scale

| Token                 | Value |
| --------------------- | ----- |
| `--z-top`             | 9999  |
| `--z-bottom-notice`   | 1450  |
| `--z-tooltip`         | 1300  |
| `--z-popover`         | 1200  |
| `--z-modal`           | 1100  |
| `--z-hedgehog-buddy`  | 1050  |
| `--z-drawer`          | 900   |
| `--z-main-nav`        | 750   |
| `--z-lemon-sidebar`   | 700   |
| `--z-top-navigation`  | 550   |
| `--z-content-overlay` | 500   |
| `--z-raised`          | 5     |

## Animations

- Focus ring transition: `box-shadow 0.1s ease-in-out`
- Modal transition: 200ms
- Fade in: 0.4s ease-out
- Overlay fade: 0.2s ease-out
- Disabled opacity: 0.65 (`--opacity-disabled`)

## Component Library

Three-tier architecture:

1. **Primitives** (`frontend/src/lib/ui/`) — Low-level React primitives (Button, Combobox, DropdownMenu, etc.)
2. **Lemon UI** (`frontend/src/lib/lemon-ui/`) — 50+ published components (LemonButton, LemonInput, LemonModal, LemonTable, etc.)
3. **Composed components** (`frontend/src/lib/components/`) — Feature-specific composed components built on Lemon UI

Always prefer Lemon UI components over custom implementations.
