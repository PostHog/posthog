# @posthog/quill

PostHog's UI primitives, components, and design tokens, bundled as one
publishable package. Built on [base-ui](https://base-ui.com/),
[Tailwind v4](https://tailwindcss.com/), and a shared token layer.

## Install

```sh
pnpm add @posthog/quill
```

Peer deps (already declared on this package, your package manager will
pull them in): `react`, `react-dom`, `tailwindcss@^4`.

## Required CSS imports

Quill ships **four** CSS entry points. They all need to be imported in
your Tailwind entry stylesheet, in order:

```css
@import 'tailwindcss';

@import '@posthog/quill/tokens.css'; /* design tokens — :root + .dark CSS vars + @theme inline */
@import '@posthog/quill/base.css'; /* one-line preflight reset (`* { @apply border-border outline-ring/50 }`) */
@import '@posthog/quill/primitives.css'; /* BEM component styles (.quill-popover__content, .quill-menu__content, …) */
@import '@posthog/quill/tailwind.css'; /* @source directive — tells Tailwind to scan quill's compiled JS */
```

Each file is small and load-bearing in a different way. Skipping any one
of them will leave components rendering unstyled or with the wrong
theme. **Do not** drop `primitives.css` thinking Tailwind will compile
the BEM rules — it won't, those rules are pre-built CSS shipped with the
package.

### Why each file exists

| File             | Provides                                                                                                                                                                                                                                                                               | What breaks without it                                                                                                                                                                                               |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tokens.css`     | `:root { --background, --foreground, --card, …, --radius, --shadow-* }` and dark-mode overrides under `.dark`/`[theme="dark"]`. Plus `@theme inline { --color-background: var(--background); … }` so Tailwind utilities like `bg-background`, `text-foreground`, `rounded-md` resolve. | Components fall back to `currentColor` / `transparent`. Theme variants (`dark:`) don't switch.                                                                                                                       |
| `base.css`       | A single `@layer base { * { @apply border-border outline-ring/50 } }` rule.                                                                                                                                                                                                            | Primitives that author plain `border` (no color modifier) end up with `currentColor` borders → most bordered components look broken.                                                                                 |
| `primitives.css` | All BEM component styles — `.quill-popover__content`, `.quill-menu__content`, `.quill-tabs__indicator`, `.quill-combobox__item`, `.quill-toggle-group__item`, etc. About 80kb of pre-compiled CSS.                                                                                     | Components mount correct DOM but appear unstyled — popups have no border/shadow, menus have no padding, toggles have no pressed state, etc.                                                                          |
| `tailwind.css`   | An `@source "./**/*.js"` directive (relative to its on-disk location in `node_modules/@posthog/quill/dist`) that tells your Tailwind v4 instance to scan quill's compiled JS for class-name strings (cva variants, `cn()` calls, etc.).                                                | Tailwind utilities used inside quill primitives (e.g. `aria-selected:bg-fill-selected` on combobox items, `data-highlighted:ring-2` on autocomplete items) don't get generated → conditional states have no styling. |

### Workaround for Tailwind v4 + `@config` legacy mode

If you load a legacy `tailwind.config.js` via `@config "./tailwind.config.js"`
in your CSS, Tailwind appears to ignore `@source` directives nested
inside imported files. The `@source` in `tailwind.css` will not run.
Add an explicit `@source` line in your own CSS pointing at quill's
dist:

```css
/* Adjust the relative path so it resolves from THIS file's location to
 * your app's `node_modules/@posthog/quill/dist`. */
@source "../../../../node_modules/@posthog/quill/dist/**/*.js";
```

If you're not using `@config`, the `@source` inside `tailwind.css` runs
normally and you don't need this line.

### Cascade layer order

Tailwind v4 declares `@layer theme, base, components, utilities;`
internally. If you also use a third-party theme that uses `@import
"…" layer(name)`, you may need to declare your own layer order _first_
so the third-party layer doesn't get pushed to the front:

```css
@layer theme, base, radix, components, utilities;

@import '@radix-ui/themes/styles.css' layer(radix);
@import 'tailwindcss';

@import '@posthog/quill/tokens.css';
@import '@posthog/quill/base.css';
@import '@posthog/quill/primitives.css';
@import '@posthog/quill/tailwind.css';
```

This ensures Tailwind preflight (`base`) loads before radix's component
defaults (`radix`), which load before consumer + quill utilities
(`utilities`).

## Dark mode

Quill flips its CSS variables under either:

- the `.dark` class on `<html>` (or any ancestor), or
- the `[theme="dark"]` attribute

Use whichever your app prefers. To activate Tailwind's `dark:` variant
to track the same signal:

```css
@custom-variant dark (&:where(.dark, .dark *));
```

Drop this in your CSS entry after `@import "tailwindcss"`.

## Scoped install

If you can't load quill globally (e.g. embedding in a page that already
has its own design system), import the `.scoped.css` variants instead:

```css
@import '@posthog/quill/tokens.scoped.css';
@import '@posthog/quill/base.scoped.css';
@import '@posthog/quill/color-system.scoped.css';
```

These variants gate every selector behind `[data-quill]` so quill's
tokens and resets only apply inside subtrees marked with that
attribute. Drop `data-quill` on your wrapper element. Note that
`primitives.css` and `tailwind.css` are **not** scoped — primitives
already carry `data-quill` on their roots so their styles are naturally
locality-scoped via descendant selectors.

## Usage

```tsx
import { Button, Combobox, Dialog, Tabs } from '@posthog/quill'

function App() {
  return <Button variant="outline">Click me</Button>
}
```

All components are tree-shakeable named exports off the package root.

## Components

See [base-ui's docs](https://base-ui.com/) for the underlying primitive
API. Quill's wrappers add styling and a `data-slot` attribute; the
underlying props pass through.

## Tokens

`@posthog/quill-tokens` is published independently and re-exported from
this package (under `tokens.css` and `color-system.css`). If you only
need the design tokens (e.g. for a non-React renderer), depend on
`@posthog/quill-tokens` directly.

## Theming

Override any of the theme knobs on `:root` (or on a subtree) in your
own CSS:

```css
:root {
  --radius: 0.375rem; /* default 0.58rem */
  --theme-hue: 200; /* default 90 */
  --theme-tint: 0.02; /* default 0.006 */
  --primary-light: oklch(0.65 0.21 220); /* brand color, light */
  --primary-dark: oklch(0.83 0.16 220); /* brand color, dark */
}
```

`--theme-hue` and `--theme-tint` are inputs to the surface-color
formula in `tokens.css`. The `--primary-*` pair is the brand color.

## Versioning

Quill follows semver, with `-beta.N` and `-alpha.N` prereleases. The
public API (component props, exports) follows semver; CSS class names
and `data-slot` attributes are best-effort but not guaranteed across
minor versions — use the JSX API.
