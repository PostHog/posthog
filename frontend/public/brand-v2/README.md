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

## Using the React components

For in-app UI, prefer the inline-SVG components in
[`frontend/src/lib/brand/v2/`](../../src/lib/brand/v2/) — they avoid an extra request. Import
from the `lib/brand/v2` barrel.

Each component is a **faithful 1:1 of its source SVG** — colors and paths are exactly as
exported (only internal SVG ids are namespaced so multiple instances can't collide). Theme
adaptation is done by **swapping whole variants, never by recoloring**.

### Naming

`Logo*` = full lockup (icon + wordmark), `Logomark*` = icon only, `Wordmark*` = the "PostHog"
text only. `*Portrait` stacks the icon above the wordmark; otherwise it's landscape.

A **bare name is theme-adaptive**; an **explicit treatment is the exact, fixed asset**:

| Component                                                                              | Behavior                                   | Source asset(s)                                 |
| -------------------------------------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------- |
| `PostHogLogo`                                                                          | Adaptive: gradient in light, white in dark | `primary_logo_landscape` ↔ `logo_white`         |
| `PostHogLogoPortrait`                                                                  | Adaptive portrait                          | `primary_logo_portrait` ↔ `logo_portrait_white` |
| `PostHogLogomark`                                                                      | Gradient icon — used on both themes        | `icon_gradient.svg`                             |
| `PostHogLogoGradient`                                                                  | Fixed gradient lockup                      | `primary_logo_landscape.svg`                    |
| `PostHogLogoGradientAlt`                                                               | Fixed secondary gradient                   | `logo_gradient_2.svg`                           |
| `PostHogLogoColor`                                                                     | Fixed flat color                           | `logo_color.svg`                                |
| `PostHogLogoBlack`                                                                     | Fixed solid black (light bg)               | `logo_black.svg`                                |
| `PostHogLogoWhite`                                                                     | Fixed solid white (dark bg)                | `logo_white.svg`                                |
| `PostHogLogoGradientPortrait` / `…ColorPortrait` / `…BlackPortrait` / `…WhitePortrait` | Fixed portrait lockups                     | `logo_portrait_*.svg`                           |
| `PostHogLogomarkColor`                                                                 | Fixed color icon                           | `icon_color.svg`                                |
| `PostHogWordmarkWhite`                                                                 | Wordmark text, white                       | `wordmark_white.svg`                            |

### How the adaptive swap works

`PostHogLogo` renders both the gradient and white assets and toggles them with Tailwind's
`dark:` variant, which PostHog wires to the `[theme="dark"]` attribute on `<body>`
(`darkMode: ['selector', '[theme="dark"]']`). No JavaScript, no recoloring — just the correct
pre-made asset shown per theme. The gradient logomark reads on both backgrounds, so it isn't
swapped.

```tsx
import { PostHogLogo, PostHogLogomark, PostHogLogoColor } from 'lib/brand/v2'

// Adaptive lockup — gradient in light mode, white in dark mode, automatically
<PostHogLogo className="h-7 w-auto" />

// Gradient icon only (compact / favicon-style) — same on both themes
<PostHogLogomark className="h-8 w-8" />

// A fixed treatment when you need a specific one (e.g. flat color for print surfaces)
<PostHogLogoColor className="h-7 w-auto" />
```

Preview them all in Storybook under **Components → Brand Logos (Redesign)** (flip the theme
toolbar to watch the adaptive ones swap).
