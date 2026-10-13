import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'

// The package defaults its font URL to cdn.jsdelivr.net. We serve the file ourselves so that an open
// CDN stays out of the app's `font-src`: there it is both a wider font-parser surface and exactly the
// remote origin a CSS-injection exfiltration needs. Call this instead of the package, so a new call
// site cannot reintroduce the default.
//
// The family name has to match the `font-family` our CSS declares for flag glyphs.
const FONT_FAMILY = 'Emoji Flags Polyfill'
const FONT_URL = '/static/fonts/TwemojiCountryFlags.woff2'

export function polyfillCountryFlags(): boolean {
    return polyfillCountryFlagEmojis(FONT_FAMILY, FONT_URL)
}
