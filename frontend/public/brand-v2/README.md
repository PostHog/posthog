# PostHog logos (redesign)

Redesigned PostHog brand logos, added **alongside** the existing assets — nothing here
replaces the current logo. The original logos still live at
[`frontend/public/posthog-logo.svg`](../posthog-logo.svg) and friends, and the original
React components stay in [`frontend/src/lib/brand/`](../../src/lib/brand/). Opt into the
redesign by using the files/components below.

## Which variant to use

| Variant                  | Files                                                       | When to use                                                                      |
| ------------------------ | ----------------------------------------------------------- | -------------------------------------------------------------------------------- |
| **Primary (gradient)**   | `primary_logo_landscape.*`, `primary_logo_portrait.*`       | Default. Use wherever you'd show the brand logo.                                 |
| **Gradient (2-color)**   | `logo_gradient_2.svg`, `logo_gradient.png`                  | Alternative gradient lockup.                                                     |
| **Full color (4-color)** | `logo_color.*`, `logo_portrait_color.*`, `icon_color.*`     | Print only, or when the intersecting-gradient version can't be used.             |
| **Monochrome black**     | `logo_black.*`, `logo_portrait_black.*`                     | Light backgrounds when a monochrome logo is needed but multi-color is preferred. |
| **Monochrome white**     | `logo_white.*`, `logo_portrait_white.*`, `wordmark_white.*` | Dark backgrounds — always.                                                       |
| **Icon only**            | `icon_color.*`, `icon_gradient.*`                           | Favicon and very small sizes where the intersecting gradients are too busy.      |

Orientation: `landscape` / no suffix = horizontal (icon + wordmark side by side);
`portrait` = stacked (icon above wordmark); `icon` = mark only; `wordmark` = text only.

Each variant ships as both `.svg` (preferred — scalable) and `.png` (raster fallback).

## Using the raw assets

The frontend build serves these as URLs (esbuild `file` loader), same as the existing logos:

```tsx
import logoUrl from 'public/brand-v2/primary_logo_landscape.svg'
;<img src={logoUrl} alt="PostHog" className="h-6 w-auto" />
```

## Using the React component

For in-app UI, use the inline-SVG component in
[`frontend/src/lib/brand/v2/PostHogLogo.tsx`](../../src/lib/brand/v2/PostHogLogo.tsx) — copied
from posthog.com (the canonical source) so the app and the website stay in sync. It's a single
props-based component; import from the `lib/brand/v2` barrel.

```tsx
import { PostHogLogo } from 'lib/brand/v2'
;<PostHogLogo className="h-7 w-auto" />
```

### Props

| Prop        | Type                              | Default      | Notes                                                                                         |
| ----------- | --------------------------------- | ------------ | --------------------------------------------------------------------------------------------- |
| `variant`   | `'gradient' \| 'print' \| 'mono'` | `'gradient'` | `print` = flat 4-color; `mono` = single color.                                                |
| `color`     | `string`                          | `'black'`    | Only for `variant="mono"`: `'black'`, `'white'`, `'primary'` (theme-aware), or any CSS color. |
| `wordmark`  | `boolean`                         | `true`       | `false` = icon only.                                                                          |
| `stacked`   | `boolean`                         | `false`      | `true` = portrait (icon above wordmark).                                                      |
| `code`      | `boolean`                         | `false`      | Use the "PostHog Code" wordmark.                                                              |
| `className` | `string`                          | `''`         | Size it here, e.g. `h-7 w-auto`.                                                              |

### Theme adaptation

For a mark that follows the active theme, use `variant="mono" color="primary"` — that renders
with the `fill-primary` utility, which resolves to `var(--color-text-primary)` and flips with
the `[theme="dark"]` attribute PostHog sets on `<body>`. (This utility was added to the shared
Tailwind config to match posthog.com.) The `gradient` and `print` variants are fixed-color and
read on both light and dark backgrounds; `color="white"` / `color="black"` are fixed monochrome.

```tsx
// Theme-following monochrome mark — no manual class needed
<PostHogLogo variant="mono" color="primary" className="h-7 w-auto" />

// Icon only, portrait, etc.
<PostHogLogo wordmark={false} className="h-8 w-8" />
<PostHogLogo stacked className="h-20 w-auto" />
```

Preview the variants in Storybook under **Components → Brand Logos (Redesign)**.
