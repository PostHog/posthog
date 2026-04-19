# Quill — PostHog's unified design system

A React component library powering PostHog's unified UI surfaces (web, MCP, electron), built on Base UI and shadcn primitives. **Quill requires Tailwind v4 on the consumer side** — the library ships component source and theme metadata, and your app's Tailwind compiles the utilities into your own CSS bundle.

## Packages

Quill publishes two independent packages to npm. Everything else in `packages/quill/packages/*` is internal workspace infrastructure and never ships.

| Package                 | Description                                                                                                                                                         |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `@posthog/quill`        | The library — React components, bundled types, and three small CSS files that wire quill into your Tailwind build. Install this.                                    |
| `@posthog/quill-tokens` | Typed JavaScript exports of the design tokens (semantic colors, spacing, shadows, etc.) for consumers who want programmatic access outside of components. Optional. |

`@posthog/quill` is self-contained for styling purposes — tokens are bundled into `dist/tokens.css`, so consumers don't also need `@posthog/quill-tokens` unless they want the typed JS exports.

## Getting started

### 1. Install

```bash
pnpm add @posthog/quill
```

Tailwind v4 is a **peer dependency**. If you don't already have it:

```bash
pnpm add -D tailwindcss @tailwindcss/vite
```

(Use the PostCSS or CLI integration instead of `@tailwindcss/vite` if your bundler isn't Vite.)

### 2. Wire up the CSS

Quill ships three small stylesheets. Import them from your app's Tailwind entry — usually `globals.css`, `app.css`, or wherever you already have `@import "tailwindcss"`.

```css
@import 'tailwindcss';

@import '@posthog/quill/tokens.css'; /* design tokens (CSS vars + @theme) */
@import '@posthog/quill/base.css'; /* one border-color reset rule */
@import '@posthog/quill/tailwind.css'; /* @source directive pointing at quill's dist */
```

**What each file does:**

- `tokens.css` — registers every quill design token (`--color-*`, `--text-*`, `--leading-*`, `--radius-*`, `--shadow-*`, `--spacing`, …) with your Tailwind compiler so that utilities like `bg-fill-hover`, `text-muted-foreground`, and `rounded-md` resolve correctly. Also contains the light/dark CSS custom property values at `:root` and `.dark`.
- `base.css` — one `@layer base { * { border-border outline-ring/50 } }` reset. Load-bearing: primitives write plain `border` (no colour modifier) expecting the default border colour to be `--color-border`. Without this, Tailwind v4 falls back to `currentColor` and every bordered primitive looks broken.
- `tailwind.css` — a single `@source "./**/*.js"` directive. When your Tailwind v4 processes the import, it resolves that glob **relative to the file's on-disk location inside `node_modules/@posthog/quill/dist`**, so it scans quill's compiled library JS for class-name strings and generates the matching utilities in your own `utilities` layer. No pre-compiled stylesheet, no cascade-layer fight with your own Tailwind output.

### 3. Cascade layer order (usually optional)

If you import CSS from other libraries into named layers (e.g. `@import "@radix-ui/themes/styles.css" layer(radix)`), make sure your layer order puts those library layers _after_ `base` (so library defaults beat Tailwind's preflight) and _before_ `utilities` (so your own `className` overrides still win):

```css
@layer theme, base, radix, components, utilities;

@import '@radix-ui/themes/styles.css' layer(radix);
@import 'tailwindcss';

@import '@posthog/quill/tokens.css';
@import '@posthog/quill/base.css';
@import '@posthog/quill/tailwind.css';
```

Quill itself is **not** layered — its utilities land in the top-level `utilities` layer alongside yours, which is what makes consumer overrides via `className` Just Work.

### 4. Using the `@config` legacy bridge? Two extra lines

If your project still runs Tailwind v4 in `@config "tailwind.config.js"` legacy-compat mode (common when migrating from v3), the legacy mode has two quirks quill works around but cannot hide:

1. **It ignores `@source` directives nested inside `@import`ed CSS files.** Add an explicit `@source` pointing at quill's dist next to the imports:

   ```css
   @source "../../../../node_modules/@posthog/quill/dist/**/*.js";
   ```

   Adjust the relative path so it resolves from your CSS entry to `node_modules/@posthog/quill/dist`. Yes, it's fragile — if you can, migrate off `@config` and delete this line.

2. **It strips Tailwind v4's default `@theme` values.** Quill's `tokens.css` ships the defaults it depends on (`--leading-*`, `--tracking-*`, `--font-weight-*`) inline so primitives like `text-xs/relaxed`, `tracking-tight`, and `font-medium` still resolve. Nothing to do on your side — this just explains why `tokens.css` is larger than you'd expect.

### 5. Set up dark mode

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

### 6. Theme the palette (optional)

Quill's surface and brand colours are driven by four CSS custom properties. Override them at `:root` to reskin the whole app, or on any element to reskin just that subtree — no rebuild, no JS.

| Variable           | Default | What it controls                                                                               |
| ------------------ | ------- | ---------------------------------------------------------------------------------------------- |
| `--theme-hue`      | `90`    | OKLCH hue for **light-mode surfaces**: background, card, popover, muted, accent, border, input |
| `--theme-dark-hue` | `264`   | OKLCH hue for **dark-mode surfaces**                                                           |
| `--theme-tint`     | `0.006` | OKLCH chroma intensity for neutral surface tinting (`0` = pure grey)                           |
| `--primary-hue`    | `37.89` | OKLCH hue for the brand / primary colour                                                       |

Global override — reskin the entire app:

```css
:root {
  --theme-hue: 200; /* cool blue neutrals */
  --primary-hue: 145; /* green brand */
}
```

Subtree override — theme one section differently. Any valid CSS selector works, and Tailwind v4 arbitrary properties let you do it inline:

```tsx
<aside className="[--theme-hue:300] bg-muted">
  {/* every quill surface inside this aside shifts to a magenta tint */}
</aside>
```

**What is and isn't themeable:**

- ✅ **Surfaces** (background, card, popover, muted, accent, border, input) and their foregrounds — derived from `--theme-hue` + `--theme-tint`
- ✅ **Primary / brand** — derived from `--primary-hue`
- ❌ **Status colours** (destructive, success, warning, info) — fixed by semantic meaning; a red error should stay red regardless of brand hue
- ❌ **Secondary** — neutral dark by design

### 7. Use components

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

See the [Storybook](#development) for the full component catalogue, props, and live variants — it's the source of truth and always matches what's shipped.

## Overriding quill styles

Quill is designed so that consumer `className` wins over primitive defaults, without `!important` or specificity tricks. Every primitive routes its classes through `cn()` (`clsx` + `tailwind-merge`), so the consumer's string is deduplicated against quill's defaults at authoring time:

```tsx
// h-7 px-2 text-xs/relaxed is quill's default. The overrides below replace
// each conflicting utility individually while keeping everything else.
<Button className="h-10 px-6 text-sm">bigger button</Button>
```

For variant-level customisation, import quill's `cva` variants and compose your own wrapper locally:

```tsx
import { buttonVariants } from '@posthog/quill'
import { cn } from '@/lib/utils'

export function GhostButton({ className, ...props }) {
  return (
    <button
      className={cn(buttonVariants({ variant: 'link-muted', size: 'sm' }), 'hover:underline', className)}
      {...props}
    />
  )
}
```

For structural swaps, quill primitives built on Base UI inherit its `render` prop, which lets you replace the underlying element while keeping the primitive's behaviour and classes.

## Using the design tokens directly

If you want programmatic access to quill's semantic colour definitions — for example to theme a non-quill component or generate previews — install the tokens package separately:

```bash
pnpm add @posthog/quill-tokens
```

```ts
import { semanticColors, spacing, spacingPx, shadow } from '@posthog/quill-tokens'

// spacing is a function that computes at any step, not a lookup table:
spacing(4) // '1rem'  — for CSS-in-JS
spacingPx(4) // 16    — for React Native / Figma plugins
```

Most apps won't need this — the CSS custom properties (`var(--primary)`, `var(--background)`, `var(--border)`, …) from `tokens.css` are usually enough.

## CSS architecture

Quill follows the **shadcn-style build model**: the library ships component source and theme metadata, and the consumer's Tailwind does all the utility compilation. There is no pre-compiled utility stylesheet inside `@posthog/quill`.

```text
@posthog/quill-tokens          →  Raw design token values (TS, CSS)
@posthog/quill dist/index.js   →  Compiled library code — class strings preserved as literals
@posthog/quill dist/tokens.css →  :root / .dark vars + Tailwind v4 @theme inline block
@posthog/quill dist/tailwind.css → @source "./**/*.js" — points Tailwind's scanner at the dist
Your app                       →  Imports the three CSS files, runs Tailwind v4,
                                  emits a single CSS bundle containing your utilities
                                  and quill's utilities in one `utilities` layer
```

**Why this model?** The previous pre-compiled-stylesheet approach had a structural problem: any app that also used Tailwind shipped _two_ `utilities` layers, and the layer order fight made consumer overrides unpredictable. Layer-wrapping quill in a named layer was a band-aid that broke any time cascade order changed.

The shadcn model has no such fight because there is only one Tailwind build: the consumer's. Quill's classes and the consumer's classes live in the same layer, deduplicated through `tailwind-merge`, and ordered by Tailwind's canonical sort. Consumer overrides work by construction, not by specificity hack.

**Tree shaking**: better, not worse. Consumer Tailwind only emits classes actually reached from their code plus the quill components they import. Unused quill utilities never land in the final CSS.

## Development

Quill lives inside the PostHog monorepo. Clone, install dependencies at the repo root, and run:

```bash
# Build quill + tokens
pnpm quill:build

# Dev loop: storybook with HMR for everything
pnpm quill:storybook
```

The storybook command runs:

1. `@posthog/quill-tokens build` — generates the initial token CSS so storybook has something to import at start-up.
2. `@posthog/quill-storybook storybook` — the dev server.

Inside storybook's Vite config:

- **`@source` globs scan primitive/component/block `src/*.{ts,tsx}` directly.** Any `.tsx` edit under `packages/{primitives,components,blocks}/src` hot-reloads within a couple hundred ms — Tailwind's vite plugin catches the file change, rescans, and emits new utilities. No intermediate quill-dist rebuild.
- **`quillTokensWatcher` plugin** watches `packages/tokens/src/*.ts`. Editing a token source file (colors, spacing, typography) reruns `tsx src/build.ts`, regenerates `@posthog/quill-tokens/dist/*.css`, and triggers a full page reload so the new custom property values are live.
- **React HMR** handles story and component code changes the usual way.

In short: edit anything under `packages/*/src/**`, see the result in the browser without rebuilding quill's dist. The dist artifacts (`dist/index.js`, `dist/tokens.css`, `dist/tailwind.css`) are **only** for external consumers pulling from npm.

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
3. **Build** — installs the quill workspace with pnpm and runs `pnpm quill:build`. The `@posthog/quill` aggregate's build step emits `dist/tokens.css`, `dist/base.css`, `dist/tailwind.css`, then Vite bundles the JS by inlining the source of the internal `-primitives`, `-components`, and `-blocks` workspace packages into a single `dist/index.js` and a single rolled-up `dist/index.d.ts`. **Class-name strings are left as literals in the bundled JS** — this is what makes consumer-side Tailwind scanning work.
4. **Publish** — loops over the two public packages: `@posthog/quill-tokens`, then `@posthog/quill`.
5. **Notify** — posts success/failure and the published versions to the client-libraries Slack channel.

### Versioning

There's no changesets or semantic-release setup — versions are bumped manually. To cut a release:

1. Bump `version` in `packages/quill/packages/tokens/package.json` and/or `packages/quill/packages/quill/package.json`.
2. Merge to `master`.
3. Go to Actions → "Publish Quill npm packages" → Run workflow → pick `alpha` or `latest`.

## Component checklist

- [x] Tokens (colors, shadows, spacing, typography)
- [x] Primitives (40+ components with Storybook stories)
- [ ] Components (composed primitives — in progress)
- [ ] Blocks (product elements — in progress)
