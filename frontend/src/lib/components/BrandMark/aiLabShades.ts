export type AiLab = 'Anthropic' | 'OpenAI' | 'Google' | 'xAI' | 'Cursor' | 'Open weights'

// Five shades per lab, dark to light. Each ramp keeps one hue and steps lightness evenly in OKLCH
// (L 0.46 to 0.82, chroma 0.13), so every lab's shades look equally far apart and stay readable on
// light and dark backgrounds. The posthog.com MCP leaderboard uses the same hues.
export const AI_LAB_SHADES: Record<AiLab, readonly string[]> = {
    Anthropic: ['#913814', '#af5331', '#cd6e4c', '#ec8a67', '#ffad90'],
    OpenAI: ['#0c665a', '#008474', '#08a28f', '#14c2ab', '#49dfc7'],
    Google: ['#025c93', '#1777b8', '#3b93d5', '#59aff4', '#8fcbfe'],
    xAI: ['#695700', '#86700a', '#a58a07', '#c1a637', '#dec358'],
    Cursor: ['#59479a', '#7262b7', '#8c7dd5', '#a799f3', '#c3bafe'],
    'Open weights': ['#85356e', '#a25089', '#bf6aa5', '#dd86c1', '#fca2df'],
}

// The middle shade, which a lab's single series or mark uses.
export const MAIN_LAB_SHADE = 2
