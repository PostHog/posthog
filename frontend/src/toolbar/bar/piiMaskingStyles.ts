import { PostHog } from 'posthog-js'

const SHIMMER_EFFECT_CSS = `
    @keyframes shimmer {
        0% {
            background-position: -200% 0;
        }
        100% {
            background-position: 200% 0;
        }
    }
`

interface Color {
    r: number
    g: number
    b: number
}

const lighten = (color: Color, amount: number): Color => {
    const newR = Math.min(255, color.r + amount)
    const newG = Math.min(255, color.g + amount)
    const newB = Math.min(255, color.b + amount)
    return { r: newR, g: newG, b: newB }
}

const darken = (color: Color, amount: number): Color => {
    const newR = Math.max(0, color.r - amount)
    const newG = Math.max(0, color.g - amount)
    const newB = Math.max(0, color.b - amount)
    return { r: newR, g: newG, b: newB }
}

const parseColorFromHex = (hex: string): Color => {
    const r = parseInt(hex.substring(0, 2), 16)
    const g = parseInt(hex.substring(2, 4), 16)
    const b = parseInt(hex.substring(4, 6), 16)
    return { r, g, b }
}

const colorToHex = (color: Color): string => {
    return `#${color.r.toString(16).padStart(2, '0')}${color.g.toString(16).padStart(2, '0')}${color.b.toString(16).padStart(2, '0')}`
}

const getColorPalette = (color: string): [Color, Color, Color, Color, Color] => {
    const hex = color.replace('#', '')
    const baseColor = parseColorFromHex(hex)

    const color1 = darken(baseColor, 30)
    const color2 = darken(baseColor, 15)
    const color3 = baseColor
    const color4 = lighten(baseColor, 15)
    const color5 = darken(baseColor, 15)

    return [color1, color2, color3, color4, color5]
}

const generatePiiMaskingCSSForSelector = (
    selector: string,
    colors: [string, string, string, string, string]
): string => {
    return `
        ${selector} {
            position: relative !important;
        }
        ${selector}::before {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(
                90deg,
                ${colors[0]} 0%,
                ${colors[1]} 20%,
                ${colors[2]} 40%,
                ${colors[3]} 60%,
                ${colors[4]} 80%,
                ${colors[0]} 100%
            );
            background-size: 200% 100%;
            animation: shimmer 6s ease-in-out infinite;
            z-index: 999999;
            pointer-events: none;
        }
        ${selector} img,
        ${selector} video {
            opacity: 0 !important;
        }
        ${selector} * {
            color: transparent !important;
            text-shadow: none !important;
        }
    `
}

export const generatePiiMaskingCSS = (baseColor: string, posthog: PostHog | null): string => {
    const [color1, color2, color3, color4, color5] = getColorPalette(baseColor).map(colorToHex)

    // There's some checks that can be a regexp or even done via JS which means we can't do it CSS based
    // We're ok with that for now, but we should consider reworking this in the future
    // to make use of ResizeObserver to detect changes in the DOM and update the CSS accordingly
    const selectors = new Set<string>(['.ph-no-capture', '.ph-sensitive'])
    if (posthog) {
        selectors.add(
            typeof posthog.config.session_recording?.blockClass === 'string'
                ? `.${posthog.config.session_recording?.blockClass}`
                : '.ph-no-capture'
        )
        selectors.add(
            typeof posthog.config.session_recording?.maskTextClass === 'string'
                ? `.${posthog.config.session_recording?.maskTextClass}`
                : '.ph-mask'
        )
        if (typeof posthog.config.session_recording?.maskTextSelector === 'string') {
            selectors.add(posthog.config.session_recording?.maskTextSelector)
        }
        if (posthog.config.session_recording?.maskAllInputs === true) {
            selectors.add('input, textarea')
        }
    }

    const selectorsCss = Array.from(selectors)
        .map((selector) => generatePiiMaskingCSSForSelector(selector, [color1, color2, color3, color4, color5]))
        .join('\n')

    return `
        ${SHIMMER_EFFECT_CSS}
        ${selectorsCss}
    `
}

export const PII_MASKING_PRESET_COLORS = [
    { label: 'Grey', value: '#888888' },
    { label: 'Red', value: '#aa7777' },
    { label: 'Blue', value: '#7788aa' },
    { label: 'Green', value: '#88aa88' },
    { label: 'Purple', value: '#9988aa' },
    { label: 'Orange', value: '#aa9988' },
] as const
