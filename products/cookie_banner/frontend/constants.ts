import type { CookieBannerAppearanceApi } from './generated/api.schemas'

// Keep in sync with DEFAULT_APPEARANCE in products/cookie_banner/backend/constants.py —
// the backend merges these same defaults into the banner served to customer sites.
export const DEFAULT_APPEARANCE: Required<CookieBannerAppearanceApi> = {
    title: 'We use cookies',
    description:
        'We use cookies to understand how you use our site and to improve your experience. You can accept or decline analytics cookies below.',
    acceptButtonText: 'Accept',
    declineButtonText: 'Decline',
    artStyle: 'posthog-logo',
    position: 'bottom-right',
    backgroundColor: '#eeefe9',
    textColor: '#151515',
    buttonColor: '#f54e00',
    buttonTextColor: '#ffffff',
    whiteLabel: false,
}

export const ART_STYLE_LABELS: Record<Required<CookieBannerAppearanceApi>['artStyle'], string> = {
    none: 'No art',
    'posthog-logo': 'PostHog logo',
    'posthog-logomark-light': 'Light logomark',
    'hedgehog-builder': 'Builder Hog',
    'hedgehog-business': 'Enterprise Hog',
    'hedgehog-hogzilla': 'Hogzilla',
    'hedgehog-robot': 'RoboHog',
    'hedgehog-mobile': 'Mobile Hog',
    'hedgehog-zen': 'Zen Hog',
    'hedgehog-lens': 'Lens Hog',
    'hedgehog-town-crier': 'Town Crier',
    'hedgehog-wizard': 'Wizard Hog',
    'hedgehog-legal': 'Legal Hog',
}

export const POSITION_LABELS: Record<Required<CookieBannerAppearanceApi>['position'], string> = {
    'bottom-left': 'Bottom left',
    'bottom-right': 'Bottom right',
    'bottom-bar': 'Bottom bar',
}

/** Perceived-brightness check for hex colors (#rgb/#rrggbb), used to warn on low-contrast art */
export function isLightColor(hex: string): boolean {
    const raw = hex.replace('#', '')
    const full = raw.length === 3 || raw.length === 4 ? [...raw].map((c) => c + c).join('') : raw
    const r = parseInt(full.slice(0, 2), 16)
    const g = parseInt(full.slice(2, 4), 16)
    const b = parseInt(full.slice(4, 6), 16)
    if (isNaN(r) || isNaN(g) || isNaN(b)) {
        return false
    }
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6
}

// One-click theme presets applied to the four color fields; "light" mirrors DEFAULT_APPEARANCE
export const THEME_PALETTES = {
    light: {
        backgroundColor: '#eeefe9',
        textColor: '#151515',
        buttonColor: '#f54e00',
        buttonTextColor: '#ffffff',
    },
    dark: {
        backgroundColor: '#1d1f27',
        textColor: '#f3f4ef',
        buttonColor: '#f54e00',
        buttonTextColor: '#ffffff',
    },
} satisfies Record<string, Partial<CookieBannerAppearanceApi>>

export type ThemePreset = keyof typeof THEME_PALETTES
