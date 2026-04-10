# Quill — PostHog's unified design system

A React component library powering PostHog's unified UI surfaces (web, MCP, electron), built on Base UI and shadcn primitives. Ships as a single package with a pre-compiled stylesheet — **no Tailwind setup required on the consumer side**.

## Packages

Quill publishes two independent packages to npm. Everything else in `packages/quill/packages/*` is internal workspace infrastructure and never ships.

| Package                 | Description                                                                                                                                                         |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `@posthog/quill`        | The library — React components, bundled types, and the pre-compiled stylesheet. Install this.                                                                       |
| `@posthog/quill-tokens` | Typed JavaScript exports of the design tokens (semantic colors, spacing, shadows, etc.) for consumers who want programmatic access outside of components. Optional. |

`@posthog/quill` is self-contained at runtime — it does not depend on `@posthog/quill-tokens` on the consumer side. The tokens package is consumed at library build time to produce the compiled stylesheet, and its values are baked into `dist/quill.css`, so a consumer who only wants components never has to install it.

## Getting started

### 1. Install

```bash
pnpm add @posthog/quill
```

That's the only install. The library ships with its own Tailwind already compiled into `dist/quill.css`, so you don't need `tailwindcss`, `shadcn`, `tw-animate-css`, or any PostCSS plugins unless you're using Tailwind for your own app code.

### 2. Import the stylesheet once

Somewhere in your app entry (anywhere that runs before you render components):

```ts
import '@posthog/quill/styles.css'
```

This pulls in the full pre-compiled stylesheet: colour system variables (light + dark), every utility class the primitives use, `tw-animate-css` keyframes, shadcn's `@custom-variant` selectors (already expanded), and a universal `border-color` / `body` reset. Works with Vite, Next.js, Webpack, Rspack, Parcel, or a plain CSS import — anything that can `@import` a stylesheet.

If you don't use a bundler that handles CSS imports from JS, you can `@import` it from your app's own CSS instead:

```css
@import '@posthog/quill/styles.css';
```

### 3. Set up dark mode

Quill uses class-based dark mode: add a `.dark` class to any ancestor element (usually `<html>`) and every token flips automatically.

```html
<html class="dark">
  <!-- dark mode active for the whole app -->
</html>
```

Or use the built-in `ThemeProvider` for system-preference detection, `localStorage` persistence, and cross-tab sync:

```tsx
import { ThemeProvider } from '@posthog/quill'

function App() {
  return (
    <ThemeProvider defaultTheme="system">
      <YourApp />
    </ThemeProvider>
  )
}
```

`ThemeProvider` exposes a `useTheme()` hook for reading and setting the theme programmatically.

### 4. Use components

```tsx
import { Button, Card, CardHeader, CardTitle, CardContent } from '@posthog/quill'

function MyPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Hello Quill</CardTitle>
      </CardHeader>
      <CardContent>
        <Button variant="primary">Click me</Button>
        <Button variant="outline">Cancel</Button>
      </CardContent>
    </Card>
  )
}
```

The full component catalogue:

Accordion · Badge · Button · ButtonGroup · Card · CardGroup · Checkbox · Chip · Collapsible · Combobox · Command · ContextMenu · Dialog · Drawer · DropdownMenu · Empty · Field · Input · InputGroup · Item · Kbd · Label · Menubar · Popover · Progress · RadioGroup · Resizable · ScrollArea · Select · Separator · Skeleton · SkeletonText · Slider · Spinner · Switch · Tabs · Textarea · Toggle · ToggleGroup · Tooltip

## Using the design tokens directly

If you want programmatic access to quill's semantic colour definitions — for example to theme a non-quill component or generate previews — install the tokens package separately:

```bash
pnpm add @posthog/quill-tokens
```

```ts
import { semanticColors, spacing, shadow } from '@posthog/quill-tokens'
```

Most apps won't need this — the CSS custom properties (`var(--primary)`, `var(--background)`, `var(--border)`, etc.) from the main stylesheet are usually enough.

## CSS architecture

The styling contract is built on CSS custom properties:

```text
@posthog/quill-tokens    →  Defines raw values (--background: oklch(…))
@posthog/quill styles.css →  Resolves every primitive utility against those tokens at build time
Your app                 →  Imports the compiled stylesheet and renders components
```

At library build time, `@tailwindcss/cli` scans the primitives / components / blocks source trees, expands every `@custom-variant`, `shadcn/tailwind.css`, and `tw-animate-css` macro, and writes a single minified `dist/quill.css` (~120 kB). Consumers import that static file and their own bundler never runs Tailwind over quill's source.

The key property this gives you: **quill's primitive sizing cannot be overridden by the consumer's Tailwind theme**. Every `.p-4`, `.rounded-md`, `.text-sm`, `.shadow-sm` quill writes is already resolved against quill's own scales in the shipped CSS. You can still recolour the library by overriding the CSS variables (`--primary`, `--background`, etc.) at `:root` or under a custom class.

## Development

Quill lives inside the PostHog monorepo. Clone, install dependencies at the repo root, and run:

```bash
# Build the whole quill workspace (tokens → primitives → components → blocks → @posthog/quill aggregate)
pnpm quill:build

# Dev loop: token watcher + Tailwind CSS watcher + Storybook, all in parallel
pnpm quill:storybook
```

The storybook command runs three processes together:

1. `@posthog/quill-tokens build:watch` — regenerates token CSS when you edit a token source file.
2. `@posthog/quill build:css:watch` — reruns `tailwindcss` against the aggregate's input whenever a `.tsx` file under `primitives/`, `components/`, or `blocks/` changes. This writes a fresh `dist/quill.css`.
3. `@posthog/quill-storybook storybook` — the dev server. It imports `@posthog/quill/styles.css` exactly the way a real consumer would, so any change you see in Storybook is a change a downstream app will see.

HMR propagates automatically through the chain: edit a primitive, save, the Tailwind watcher rebuilds the dist CSS in ~50 ms, and Vite HMR injects the new CSS into the browser without a reload.

### Repo layout

```text
packages/quill/
├── packages/
│   ├── tokens/          @posthog/quill-tokens        (published)
│   ├── primitives/      @posthog/quill-primitives    (private, bundled into @posthog/quill)
│   ├── components/      @posthog/quill-components    (private, bundled into @posthog/quill)
│   ├── blocks/          @posthog/quill-blocks        (private, bundled into @posthog/quill)
│   └── quill/           @posthog/quill               (published — the aggregate consumers install)
└── apps/
    └── storybook/       @posthog/quill-storybook     (private, dev tool)
```

## Publishing

Quill is published to npm via a manually triggered GitHub Actions workflow: [`.github/workflows/publish-quill-npm.yml`](../../.github/workflows/publish-quill-npm.yml).

### How it works

1. **Trigger** — `workflow_dispatch` only. A maintainer runs "Publish Quill npm packages" from the Actions tab and picks an npm dist-tag (`alpha` or `latest`).
2. **Auth** — runs under the `Release` GitHub environment with `id-token: write`, publishing with npm provenance (`NPM_CONFIG_PROVENANCE: true`) via OIDC trusted publishing. No long-lived npm tokens.
3. **Build** — installs the quill workspace with pnpm and runs `pnpm quill:build`. The `@posthog/quill` aggregate's build step runs the Tailwind CLI to produce `dist/quill.css`, then Vite bundles the JS by inlining the source of the internal `-primitives`, `-components`, and `-blocks` workspace packages into a single `dist/index.js` and a single rolled-up `dist/index.d.ts`.
4. **Publish** — loops over the two public packages: `@posthog/quill-tokens`, then `@posthog/quill`. The two are independent at install time, so publish order does not matter for consumer resolution; `@posthog/quill-tokens` is built first because the aggregate's Tailwind pipeline imports its CSS files at build time.
5. **Notify** — posts success/failure and the published versions to the client-libraries Slack channel.

### Versioning

There's no changesets or semantic-release setup — versions are bumped manually. To cut a release:

1. Bump `version` in `packages/quill/packages/tokens/package.json` and/or `packages/quill/packages/quill/package.json`.
2. Merge to `master`.
3. Go to Actions → "Publish Quill npm packages" → Run workflow → pick `alpha` or `latest`.

The two packages can move independently because `@posthog/quill` does not list `@posthog/quill-tokens` as a runtime dependency — each package ships its own typed JS bundle and is versioned on its own cadence. In practice it's still simplest to bump them together when a release is cutting a new design-token value, because the compiled CSS in `@posthog/quill` will have drifted from the raw values in the live `@posthog/quill-tokens`.

## Component checklist

- [x] Tokens (colors, shadows, spacing, typography)
- [x] Primitives (40+ components with Storybook stories)
- [ ] Components (composed primitives — in progress)
- [ ] Blocks (product elements — in progress)
