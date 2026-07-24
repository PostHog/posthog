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
    'hedgehog-wave': 'Waving hedgehog',
    'hedgehog-heart': 'Hedgehog with heart',
}

export const POSITION_LABELS: Record<Required<CookieBannerAppearanceApi>['position'], string> = {
    'bottom-left': 'Bottom left',
    'bottom-right': 'Bottom right',
    'bottom-bar': 'Bottom bar',
}
