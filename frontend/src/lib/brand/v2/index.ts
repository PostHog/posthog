// Redesigned PostHog logo set. Additive — the existing lib/brand components
// (Logo, Logomark, PostHogWordmarkLogo) are unchanged. Opt in by importing from here.
//
// Naming: `Logo*` = full lockup (icon + wordmark), `Logomark*` = icon only,
// `Wordmark*` = the "PostHog" text only. `*Portrait` stacks the icon above the
// wordmark; otherwise the orientation is landscape.
//
// Theme: a *bare* name (`PostHogLogo`, `PostHogLogoPortrait`) is the theme-adaptive
// default — it shows the gradient lockup in light mode and the solid-white lockup in
// dark mode, swapped via CSS off `[theme="dark"]`. An explicit treatment in the name
// (`Gradient`, `Color`, `Black`, `White`) is the exact, fixed source asset — values
// untouched, no theme swap. The gradient logomark works on both themes, so the bare
// `PostHogLogomark` is the gradient icon.

// Theme-adaptive lockups (gradient ↔ white by theme) — the recommended defaults
export { PostHogLogo } from './PostHogLogo'
export type { PostHogLogoProps } from './PostHogLogo'
export { PostHogLogoPortrait } from './PostHogLogoPortrait'
export type { PostHogLogoPortraitProps } from './PostHogLogoPortrait'

// Fixed landscape lockups
export { PostHogLogoGradient } from './PostHogLogoGradient'
export type { PostHogLogoGradientProps } from './PostHogLogoGradient'
export { PostHogLogoGradientAlt } from './PostHogLogoGradientAlt'
export type { PostHogLogoGradientAltProps } from './PostHogLogoGradientAlt'
export { PostHogLogoColor } from './PostHogLogoColor'
export type { PostHogLogoColorProps } from './PostHogLogoColor'
export { PostHogLogoBlack } from './PostHogLogoBlack'
export type { PostHogLogoBlackProps } from './PostHogLogoBlack'
export { PostHogLogoWhite } from './PostHogLogoWhite'
export type { PostHogLogoWhiteProps } from './PostHogLogoWhite'

// Fixed portrait lockups
export { PostHogLogoGradientPortrait } from './PostHogLogoGradientPortrait'
export type { PostHogLogoGradientPortraitProps } from './PostHogLogoGradientPortrait'
export { PostHogLogoColorPortrait } from './PostHogLogoColorPortrait'
export type { PostHogLogoColorPortraitProps } from './PostHogLogoColorPortrait'
export { PostHogLogoBlackPortrait } from './PostHogLogoBlackPortrait'
export type { PostHogLogoBlackPortraitProps } from './PostHogLogoBlackPortrait'
export { PostHogLogoWhitePortrait } from './PostHogLogoWhitePortrait'
export type { PostHogLogoWhitePortraitProps } from './PostHogLogoWhitePortrait'

// Icon only — the gradient mark is used on both light and dark backgrounds
export { PostHogLogomark } from './PostHogLogomark'
export type { PostHogLogomarkProps } from './PostHogLogomark'
export { PostHogLogomarkColor } from './PostHogLogomarkColor'
export type { PostHogLogomarkColorProps } from './PostHogLogomarkColor'

// Wordmark only (white)
export { PostHogWordmarkWhite } from './PostHogWordmarkWhite'
export type { PostHogWordmarkWhiteProps } from './PostHogWordmarkWhite'
