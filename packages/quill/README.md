# Quill - PostHog's unified design system

A component library for PostHog's unified UI (MCP, Web & Electron) built with React 19, TypeScript, Tailwind CSS v4, Base UI, and based on shadcn/ui.

## Packages

| Package                     | Description                                                          |
| --------------------------- | -------------------------------------------------------------------- |
| `@posthog/quill-tokens`     | Design tokens (colors, spacing, typography, shadows) + generated CSS |
| `@posthog/quill-primitives` | Base UI components (Button, Card, Input, Dialog, etc.)               |
| `@posthog/quill-components` | Composed primitives with easy-to-use APIs                            |
| `@posthog/quill-blocks`     | Product-level elements built from components                         |

## Getting started

### 1. Install

```bash
pnpm add @posthog/quill-primitives
```

Peer dependencies:

```bash
pnpm add react react-dom tailwindcss shadcn tw-animate-css @fontsource-variable/inter
```

### 2. Set up Tailwind v4

Quill requires Tailwind v4 processing to resolve its design tokens and scan component source files for utility classes. Pick the integration that matches your bundler:

#### Vite

```bash
pnpm add -D @tailwindcss/vite
```

```ts
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
})
```

#### Next.js / Webpack / Any PostCSS-compatible bundler

```bash
pnpm add -D @tailwindcss/postcss
```

```js
// postcss.config.mjs
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
}
```

### 3. Import CSS

Two imports in your main CSS file — that's it:

```css
/* src/index.css */
@import 'tailwindcss';
@import '@posthog/quill-primitives/index.css';
```

This single quill import gives you:

- Color system CSS variables (light + dark themes)
- Tailwind theme mappings (`@theme`) for quill's design tokens
- Animation utilities (tw-animate-css)
- shadcn base styles
- Automatic scanning of quill component source for utility classes (`@source`)

You can use quill's design tokens in your own code too — classes like `bg-primary`, `text-muted-foreground`, `border-border` all work.

### 4. Set up dark mode

Quill uses class-based dark mode. Add a `.dark` class on an ancestor element:

```html
<html class="dark">
  <!-- dark mode active -->
</html>
```

Or use the built-in `ThemeProvider` for automatic handling:

```tsx
import { ThemeProvider } from '@posthog/quill-primitives'

function App() {
  return (
    <ThemeProvider defaultTheme="system">
      <YourApp />
    </ThemeProvider>
  )
}
```

`ThemeProvider` gives you:

- System preference detection (`prefers-color-scheme`)
- localStorage persistence
- Cross-tab sync
- `useTheme()` hook to read/set theme programmatically

### 5. Use components

```tsx
import { Button, Card, CardHeader, CardTitle, CardContent } from '@posthog/quill-primitives'

function MyPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Hello Quill</CardTitle>
      </CardHeader>
      <CardContent>
        <Button variant="default">Click me</Button>
        <Button variant="secondary">Cancel</Button>
      </CardContent>
    </Card>
  )
}
```

## Available components

Primitives: Accordion, Badge, Button, ButtonGroup, Card, CardGroup, Checkbox, Chip, Collapsible, Combobox, Command, ContextMenu, Dialog, Drawer, DropdownMenu, Empty, Field, Input, InputGroup, Item, Kbd, Label, Menubar, Popover, Progress, RadioGroup, Resizable, ScrollArea, Select, Separator, Skeleton, SkeletonText, Slider, Spinner, Switch, Tabs, Textarea, Toggle, ToggleGroup, Tooltip

## CSS architecture

Quill's styling is built on CSS custom properties as the contract between tokens and components:

```text
@posthog/quill-tokens        →  Defines values (--background: oklch(...))
@posthog/quill-primitives     →  Maps to Tailwind theme (@theme { --color-background: var(--background) })
Your app                      →  Uses utility classes (bg-background, text-primary)
```

The token package generates two Tailwind CSS variants:

- `tailwind.css` — For apps: includes `@theme` + `@layer base` (global resets)
- `tailwind-lib.css` — For libraries: includes only `@theme` (no global resets)

The primitives' `index.css` imports `tailwind-lib.css` (no base reset) so your app's own Tailwind preflight handles resets.

## Development

```bash
# Install dependencies
pnpm install

# Build all packages (runs in dependency order)
pnpm build

# Run Storybook
pnpm storybook
```

## Publishing

Quill is published to npm via a manually triggered GitHub Actions workflow: [`.github/workflows/publish-quill-npm.yml`](../../.github/workflows/publish-quill-npm.yml).

The umbrella `@posthog/quill` package is private — only the four sub-packages under `packages/quill/packages/*` are published:

- `@posthog/quill-tokens`
- `@posthog/quill-primitives`
- `@posthog/quill-components`
- `@posthog/quill-blocks`

### How it works

1. **Trigger** — `workflow_dispatch` only. A maintainer runs "Publish Quill npm packages" from the Actions tab and picks an npm dist-tag (`alpha` or `latest`).
2. **Auth** — runs under the `Release` GitHub environment with `id-token: write`, publishing with npm provenance (`NPM_CONFIG_PROVENANCE: true`) via OIDC trusted publishing — no long-lived npm token.
3. **Build** — installs the quill workspace with pnpm and runs `pnpm quill:build` (fans out to each sub-package's `vite build`).
4. **Publish** — loops over the four sub-packages in dependency order and runs `pnpm --filter "@posthog/$pkg" publish --tag "$NPM_TAG" --no-git-checks --access public`. Each sub-package declares `"publishConfig": { "access": "public" }` and ships `src` + `dist`.
5. **Notify** — posts success/failure and the published versions to the client-libraries Slack channel.

### Versioning

There's no changesets or semantic-release setup — versions are bumped manually. To cut a release:

1. Bump `version` in each of the four sub-package `package.json` files.
2. Merge to `master`.
3. Go to Actions → "Publish Quill npm packages" → Run workflow → pick `alpha` or `latest`.

## Component checklist

- [x] Tokens (colors, shadows, spacing, typography)
- [x] Primitives (40+ components with Storybook stories)
- [ ] Components (composed primitives — in progress)
- [ ] Blocks (product elements — in progress)
