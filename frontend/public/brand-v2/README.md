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
[`frontend/src/lib/brand/v2/`](../../src/lib/brand/v2/) — they avoid an extra request and
the monochrome one adapts to the current theme:

```tsx
import { PostHogLogoV2, PostHogLogomarkV2, PostHogWordmarkLogoV2 } from 'lib/brand/v2'

// Full-color gradient lockup
<PostHogLogoV2 className="h-7 w-auto" />

// Gradient icon only (compact / favicon-style)
<PostHogLogomarkV2 className="h-8 w-8" />

// Monochrome lockup — follows text color (use text-primary on light, text-white on dark)
<PostHogWordmarkLogoV2 className="h-6 w-auto text-primary" />
```
