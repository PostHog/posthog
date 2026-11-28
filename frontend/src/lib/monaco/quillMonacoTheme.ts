import type { editor as MonacoEditorNamespace } from 'monaco-editor'

export const QUILL_MONACO_THEME_LIGHT = 'posthog-quill-light'
export const QUILL_MONACO_THEME_DARK = 'posthog-quill-dark'

export const QUILL_THEME_TOKENS = [
    'card',
    'foreground',
    'muted-foreground',
    'subtle-foreground',
    'border',
    'fill-hover',
    'fill-selected',
    'ring',
    'primary',
    'completed-foreground',
    'success-foreground',
    'warning-foreground',
    'info-foreground',
    'destructive-foreground',
] as const

export type QuillThemeToken = (typeof QUILL_THEME_TOKENS)[number]

export type QuillColorResolver = (token: QuillThemeToken) => string | null

interface Rgba {
    r: number
    g: number
    b: number
    a: number
}

const HEX_COLOR = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i

export function parseHexColor(hex: string): Rgba | null {
    const match = HEX_COLOR.exec(hex)
    if (!match) {
        return null
    }
    const rgb = parseInt(match[1], 16)
    return {
        r: (rgb >> 16) & 0xff,
        g: (rgb >> 8) & 0xff,
        b: rgb & 0xff,
        a: match[2] ? parseInt(match[2], 16) : 255,
    }
}

function toHexByte(value: number): string {
    return Math.round(Math.min(255, Math.max(0, value)))
        .toString(16)
        .padStart(2, '0')
}

export function rgbaToHex({ r, g, b, a }: Rgba): string {
    const rgb = `#${toHexByte(r)}${toHexByte(g)}${toHexByte(b)}`
    return a >= 255 ? rgb : `${rgb}${toHexByte(a)}`
}

/** Flattens a translucent color onto an opaque background and returns `#rrggbb`. */
export function compositeOver(foreground: string, background: string): string | null {
    const fg = parseHexColor(foreground)
    const bg = parseHexColor(background)
    if (!fg || !bg) {
        return null
    }
    const alpha = fg.a / 255
    return rgbaToHex({
        r: fg.r * alpha + bg.r * (1 - alpha),
        g: fg.g * alpha + bg.g * (1 - alpha),
        b: fg.b * alpha + bg.b * (1 - alpha),
        a: 255,
    })
}

export function buildQuillMonacoTheme(
    resolve: QuillColorResolver,
    isDark: boolean
): MonacoEditorNamespace.IStandaloneThemeData {
    // Token rules take no alpha channel, so translucent tokens such as --subtle-foreground are
    // flattened onto the editor background. Without --card, fall back to the base theme's background.
    const background = resolve('card') ?? (isDark ? '#1e1e1e' : '#ffffff')

    const rules: MonacoEditorNamespace.ITokenThemeRule[] = []
    const addRule = (token: string, quillToken: QuillThemeToken, fontStyle?: string): void => {
        const color = resolve(quillToken)
        const opaque = color ? compositeOver(color, background) : null
        if (opaque) {
            // Monaco reads rule colors without the leading '#'.
            rules.push({ token, foreground: opaque.slice(1), ...(fontStyle ? { fontStyle } : {}) })
        }
    }
    addRule('', 'foreground')
    addRule('keyword', 'primary', 'bold')
    // The HogQL tokenizer emits built-in functions as 'predefined'.
    addRule('predefined', 'completed-foreground')
    addRule('function', 'completed-foreground')
    addRule('string', 'success-foreground')
    addRule('number', 'warning-foreground')
    addRule('comment', 'subtle-foreground', 'italic')
    addRule('operator', 'muted-foreground')
    addRule('delimiter', 'muted-foreground')
    addRule('identifier.quote', 'muted-foreground')
    addRule('type', 'info-foreground')
    addRule('invalid', 'destructive-foreground')

    const colors: MonacoEditorNamespace.IColors = {}
    const addColor = (key: string, quillToken: QuillThemeToken): void => {
        const color = resolve(quillToken)
        if (color) {
            colors[key] = color
        }
    }
    addColor('editor.background', 'card')
    addColor('editor.foreground', 'foreground')
    addColor('editorGutter.background', 'card')
    addColor('editorLineNumber.foreground', 'subtle-foreground')
    addColor('editorLineNumber.activeForeground', 'foreground')
    addColor('editor.lineHighlightBackground', 'fill-hover')
    // The base light theme draws a grey border around the current line, which --fill-hover replaces.
    colors['editor.lineHighlightBorder'] = '#00000000'
    addColor('editor.selectionBackground', 'fill-selected')
    addColor('editor.inactiveSelectionBackground', 'fill-hover')
    addColor('editorCursor.foreground', 'foreground')
    addColor('editorIndentGuide.background1', 'border')
    addColor('editorIndentGuide.activeBackground1', 'muted-foreground')
    addColor('editorBracketMatch.border', 'ring')
    addColor('focusBorder', 'ring')
    addColor('editorWidget.background', 'card')
    addColor('editorWidget.foreground', 'foreground')
    addColor('editorWidget.border', 'border')
    addColor('editorSuggestWidget.background', 'card')
    addColor('editorSuggestWidget.foreground', 'foreground')
    addColor('editorSuggestWidget.border', 'border')
    addColor('editorSuggestWidget.selectedBackground', 'fill-selected')
    addColor('editorSuggestWidget.highlightForeground', 'primary')
    addColor('editorHoverWidget.background', 'card')
    addColor('editorHoverWidget.foreground', 'foreground')
    addColor('editorHoverWidget.border', 'border')
    addColor('editorError.foreground', 'destructive-foreground')

    return { base: isDark ? 'vs-dark' : 'vs', inherit: true, rules, colors }
}

/** Converts any CSS color the browser can paint (oklch, color-mix, ...) to hex by reading one canvas pixel. */
export function cssColorToHex(cssColor: string, context: CanvasRenderingContext2D): string | null {
    // An invalid value leaves fillStyle unchanged, so a sentinel shows whether the browser accepted it.
    const sentinel = '#010203'
    context.fillStyle = sentinel
    context.fillStyle = cssColor
    if (context.fillStyle === sentinel && cssColor.trim().toLowerCase() !== sentinel) {
        return null
    }
    context.clearRect(0, 0, 1, 1)
    context.fillRect(0, 0, 1, 1)
    const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data
    return rgbaToHex({ r, g, b, a })
}

/**
 * Reads the quill tokens as they apply to `element`, which must sit inside the `[data-quill]` subtree
 * so that the quill light or dark values are in scope.
 */
export function createQuillColorResolver(element: HTMLElement): QuillColorResolver {
    const resolved = new Map<QuillThemeToken, string | null>()
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) {
        return () => null
    }

    // A custom property's computed value is its unresolved text, for example
    // "color-mix(in oklab, oklch(...) 80%, transparent)". Assigning it to `color` on a probe
    // makes the browser resolve it to a concrete color first.
    const probe = document.createElement('span')
    probe.style.position = 'absolute'
    probe.style.visibility = 'hidden'
    probe.style.pointerEvents = 'none'
    element.appendChild(probe)
    try {
        const elementStyle = getComputedStyle(element)
        for (const token of QUILL_THEME_TOKENS) {
            if (!elementStyle.getPropertyValue(`--${token}`).trim()) {
                // An undefined variable makes `color` fall back to the inherited value, which is wrong.
                resolved.set(token, null)
                continue
            }
            probe.style.color = `var(--${token})`
            const computed = getComputedStyle(probe).color
            resolved.set(token, computed ? cssColorToHex(computed, context) : null)
        }
    } finally {
        probe.remove()
    }
    return (token) => resolved.get(token) ?? null
}

export function defineQuillMonacoTheme(
    monaco: { editor: Pick<typeof MonacoEditorNamespace, 'defineTheme'> },
    element: HTMLElement,
    isDark: boolean
): string {
    const name = isDark ? QUILL_MONACO_THEME_DARK : QUILL_MONACO_THEME_LIGHT
    monaco.editor.defineTheme(name, buildQuillMonacoTheme(createQuillColorResolver(element), isDark))
    return name
}
