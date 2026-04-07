# UI Architecture

> Architecture reference for the quill design system inside `posthog/posthog`.

---

## 1. Monorepo overview

```text
quill/
├── packages/
│   ├── tokens/          @posthog/quill-tokens       — Source-of-truth design tokens (JS) + CSS generation
│   ├── primitives/      @posthog/quill-primitives    — Base UI components (React + Tailwind v4 + Base-UI)
│   ├── components/      @posthog/quill-components    — Composed primitives with easy-to-use APIs (what apps import)
│   └── blocks/          @posthog/quill-blocks        — Product-level patterns (FeatureFlag, Experiment, etc.)
├── apps/
│   └── storybook/       — Storybook documentation
└── package.json         — Root scripts (pnpm -r build, etc.)
```

---

## 2. Dependency graph

```text
@posthog/quill-tokens           (no dependencies — pure JS/TS)
        │
        ├──▶ @posthog/quill-primitives
        │       ├── @base-ui/react       (unstyled headless components)
        │       ├── class-variance-authority (CVA — variant class maps)
        │       ├── clsx + tailwind-merge (class merging)
        │       ├── lucide-react         (icons)
        │       └── vaul                 (drawer primitive)
        │
        ├──▶ @posthog/quill-components      (imports primitives + tokens)
        │       └── @posthog/quill-primitives
        │
        └──▶ @posthog/quill-blocks          (imports components + primitives + tokens)
                └── @posthog/quill-components

Apps (storybook) depend on components + tokens at workspace:^
```

### Inter-package references

All packages use `workspace:^` (not `workspace:*`). This resolves to the local workspace package during development, and pnpm automatically converts it to `^0.0.1` (the actual version) at publish time.

---

## 3. Token system — how CSS is generated from JS

### 3.1 Source-of-truth files (all in `packages/tokens/src/`)

| File               | Exports                               | What it defines                                                   |
| ------------------ | ------------------------------------- | ----------------------------------------------------------------- |
| `colors.ts`        | `semanticColors`, `resolveTheme()`    | 20+ semantic color pairs as `[light, dark]` tuples (OKLch/HSL)    |
| `spacing.ts`       | `spacing`                             | Spacing scale: `{ 0: '0px', 1: '4px', 2: '8px', ... 16: '64px'}`  |
| `typography.ts`    | `fontSize`, `fontFamily`              | 6 font sizes with line-heights, 2 font families (sans, mono)      |
| `shadow.ts`        | `shadow`                              | 3 shadow levels: sm, md, lg                                       |
| `border-radius.ts` | `borderRadius`                        | Static radius values (sm through full)                            |
| `css.ts`           | `cssVars()`, `cssVarsFlat()`, helpers | Utility functions that convert JS objects → CSS custom properties |

### 3.2 Generation script

**`packages/tokens/src/build.ts`** runs via `tsx src/build.ts` as the first step of `pnpm build`.

It produces three CSS files in `packages/tokens/dist/`:

| File               | Purpose                                                          |
| ------------------ | ---------------------------------------------------------------- |
| `color-system.css` | `:root` + `.dark` CSS custom properties with actual color values |
| `tailwind.css`     | `@theme` mappings + `@layer base` resets (for apps)              |
| `tailwind-lib.css` | `@theme` mappings only, no base resets (for libraries)           |

**Key insight:** Libraries never ship color values. They only ship `--color-*: var(--*)` mappings so Tailwind can generate the right utility classes. The consuming app provides the actual color values via `color-system.css`.

---

## 4. Package exports

### @posthog/quill-tokens

```json
{
  "exports": {
    ".": { "types": "./dist/index.d.ts", "import": "./dist/index.js", "require": "./dist/index.cjs" },
    "./tailwind.css": "./dist/tailwind.css",
    "./tailwind-lib.css": "./dist/tailwind-lib.css",
    "./color-system.css": "./dist/color-system.css"
  }
}
```

**JS exports:** `semanticColors`, `resolveTheme()`, `generateColorSystemCSS()`, `generateStylesCSS()`, `spacing`, `fontSize`, `fontFamily`, `borderRadius`, `shadow`, CSS utility functions, and all associated types.

### @posthog/quill-primitives

```json
{
  "exports": {
    ".": { "types": "./dist/index.d.ts", "import": "./dist/index.js", "require": "./dist/index.cjs" },
    "./index.css": "./src/index.css"
  }
}
```

**JS exports:** 40+ React components (Button, Dialog, Card, Select, etc.) plus `ThemeProvider`, `useTheme`, and `cn` utility.

**CSS export (`index.css`):** A Tailwind v4 source CSS file that consumers `@import` into their own CSS. It includes:

- `@import '@posthog/quill-tokens/color-system.css'` — actual color values
- `@import '@posthog/quill-tokens/tailwind-lib.css'` — `@theme` mappings (no base resets)
- `@import 'tw-animate-css'` — animation utilities
- `@import 'shadcn/tailwind.css'` — shadcn base styles
- `@source "./"` — tells Tailwind to scan this package's component source for utility classes

This is **source CSS, not pre-compiled**. It requires the consumer to have Tailwind v4 processing enabled (via `@tailwindcss/vite` or `@tailwindcss/postcss`). Tailwind processes all the directives in one pass, generating utility classes for both quill's components and the consumer's own code.

### @posthog/quill-components

```json
{
  "exports": {
    ".": { "types": "./dist/index.d.ts", "import": "./dist/index.js", "require": "./dist/index.cjs" }
  }
}
```

### @posthog/quill-blocks

```json
{
  "exports": {
    ".": { "types": "./dist/index.d.ts", "import": "./dist/index.js", "require": "./dist/index.cjs" }
  }
}
```

---

## 5. How primitives use tokens

Components use **Tailwind v4 utility classes** that reference the semantic token CSS variables. They never import CSS values directly.

Example from `button.tsx`:

```tsx
import { cva } from 'class-variance-authority'
import { cn } from '~/lib/utils'

const buttonVariants = cva(
  '... rounded-sm border font-medium text-base ... focus-visible:ring-2 focus-visible:ring-ring ...',
  {
    variants: {
      variant: {
        default: 'border-primary bg-primary text-primary-foreground shadow-primary/24 ...',
        destructive: 'border-destructive bg-destructive text-white ...',
        outline: 'border-input bg-popover text-foreground ...',
        ghost: 'border-transparent text-foreground data-pressed:bg-accent ...',
        // ...
      },
      size: {
        default: 'h-9 px-[calc(--spacing(3)-1px)] sm:h-8',
        sm: 'h-8 gap-1.5 px-[calc(--spacing(2.5)-1px)] sm:h-7',
        // ...
      },
    },
  }
)
```

The classes like `bg-primary`, `text-foreground`, `border-input` work because:

1. `tailwind-lib.css` maps `--color-primary: var(--primary)` in the `@theme` block
2. Tailwind v4 resolves `bg-primary` → `background-color: var(--color-primary)` → `var(--primary)`
3. The actual color value comes from `color-system.css` (`:root { --primary: oklch(...) }`)

### Component primitives

Built on **@base-ui/react** (unstyled headless components from the Base-UI library). The pattern is:

- Base-UI provides behavior, accessibility, and state management
- CVA defines the Tailwind class variants
- `cn()` (clsx + tailwind-merge) combines classes

---

## 6. How consuming apps wire everything together

### Consumer setup (external app)

The consumer needs Tailwind v4 processing. Two options:

**Vite** — add `@tailwindcss/vite`:

```ts
// vite.config.ts
import tailwindcss from '@tailwindcss/vite'
export default defineConfig({
  plugins: [react(), tailwindcss()],
})
```

**PostCSS** (Next.js, Webpack, etc.) — add `@tailwindcss/postcss`:

```js
// postcss.config.mjs
export default { plugins: { '@tailwindcss/postcss': {} } }
```

Then two CSS imports:

```css
/* app.css */
@import 'tailwindcss';
@import '@posthog/quill-primitives/index.css';
```

This gives the consumer:

- All quill components styled correctly
- All quill design tokens available in their own code (`bg-primary`, `text-muted-foreground`, etc.)
- Their own Tailwind utility classes generated normally

### Why `@source` matters

Tailwind v4 auto-detects source files in the project directory but **ignores `node_modules`** by default. The `@source "./"` directive in primitives' `index.css` explicitly tells Tailwind to scan the package's own `src/` directory for utility class usage. Without this, Tailwind wouldn't generate the CSS rules for classes used inside quill components.

### Peer dependencies

Primitives declares these as peer dependencies because they're CSS-only packages that must be resolvable from the consumer's CSS processing context (pnpm's strict isolation prevents resolving them from within the package's own `node_modules`):

- `tailwindcss` — Tailwind v4 engine
- `shadcn` — shadcn UI base styles (imported via `@import 'shadcn/tailwind.css'`)
- `tw-animate-css` — Animation utilities (imported via `@import 'tw-animate-css'`)
- `@fontsource-variable/inter` — Inter font

### For posthog/posthog specifically

Since PostHog already has its own Tailwind setup, integration would involve:

1. Import `@posthog/quill-primitives/index.css` (or its constituent imports individually)
2. Ensure `.dark` class toggling on a parent element
3. Import and use components from `@posthog/quill-primitives` or `@posthog/quill-components`

---

## 7. Build pipeline

```text
pnpm build (root)
  └── pnpm -r --filter '@posthog/quill-*' build (runs in dependency order)

      1. @posthog/quill-tokens
         ├── tsx src/build.ts   → dist/color-system.css, dist/tailwind.css, dist/tailwind-lib.css
         └── vite build         → dist/index.js, dist/index.cjs, dist/index.d.ts

      2. @posthog/quill-primitives
         └── vite build         → dist/index.js, dist/index.cjs, dist/index.d.ts + per-component .d.ts

      3. @posthog/quill-components
         └── vite build         → dist/index.js, dist/index.cjs, dist/index.d.ts

      4. @posthog/quill-blocks
         └── vite build         → dist/index.js, dist/index.cjs, dist/index.d.ts
```

### Vite config pattern

Each package has a `vite.config.ts` for library-mode builds and a `tsconfig.build.json` for type generation (without `erasableSyntaxOnly`, which `vite-plugin-dts`'s api-extractor doesn't support).

```ts
// packages/primitives/vite.config.ts
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    dts({
      tsconfigPath: resolve(__dirname, 'tsconfig.build.json'),
      exclude: ['src/**/*.stories.tsx', 'src/**/*.stories.ts'],
    }),
  ],
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      formats: ['es', 'cjs'],
      fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
    },
    rollupOptions: {
      external: [
        'react',
        'react-dom',
        'react/jsx-runtime',
        '@posthog/quill-tokens',
        '@base-ui/react',
        /^@base-ui\/react\//,
        'lucide-react',
        'cmdk',
        'sonner',
        'vaul',
        'react-resizable-panels',
        'class-variance-authority',
        'clsx',
        'tailwind-merge',
        'tw-animate-css',
        '@fontsource-variable/inter',
        'next-themes',
      ],
    },
    cssCodeSplit: false,
  },
})
```

Key decisions:

- All runtime dependencies are **externalized** — the consumer installs them
- `@posthog/quill-tokens` is externalized — primitives reference token CSS vars at runtime
- Stories are excluded from type generation
- CSS is not code-split (bundled into one file if any CSS is imported by JS)

### Build output

The JS build produces compiled ESM + CJS bundles. The CSS is shipped as **source CSS** (`src/index.css`), not pre-compiled, because:

1. Tailwind v4 directives (`@theme`, `@custom-variant`, `@source`) must be processed by the consumer's Tailwind engine
2. The consumer's Tailwind needs to scan both quill's components AND their own code in one pass
3. Pre-compiled CSS would not allow consumers to use quill's design tokens in their own Tailwind classes

---

## 8. Dark mode mechanism

- **Class-based:** `.dark` class on an ancestor element
- **Tailwind v4 custom variant:** `@custom-variant dark (&:is(.dark, .dark *));`
- **Color-scheme:** `:root { color-scheme: light; }` / `.dark { color-scheme: dark; }`
- **Components use:** `dark:bg-*` variant classes that activate under `.dark` ancestry
- **App responsibility:** Toggle `.dark` class on `<html>` or a wrapper element
- **ThemeProvider:** Built-in React component that handles localStorage persistence, system preference detection, cross-tab sync, and a keyboard shortcut (press `d` to toggle)

---

## 9. Key patterns to preserve

1. **Tokens are JS-first** — colors, spacing, typography defined as typed JS objects, CSS is derived
2. **Library vs App CSS split** — libraries ship only `@theme` mappings (no color values), apps provide the actual values via `color-system.css`
3. **`@source` directive** — primitives' `index.css` includes `@source "./"` so Tailwind scans component source files for utility classes
4. **Source CSS, not pre-compiled** — CSS is shipped as Tailwind source that the consumer's Tailwind engine processes
5. **CVA for variants** — all component variants defined via `class-variance-authority`
6. **Base-UI for behavior** — components use `@base-ui/react` for accessibility and state, not custom implementations
7. **`cn()` utility** — `clsx` + `tailwind-merge` for class composition without conflicts
8. **CSS variables as the contract** — `--primary`, `--background`, etc. are the interface between tokens and components
9. **Peer deps for CSS packages** — `shadcn`, `tw-animate-css`, `@fontsource-variable/inter` are peer dependencies because pnpm's strict isolation requires them to be resolvable from the consumer's context
