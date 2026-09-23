import type { GlyphPart } from './GlassIcon'

export interface IconGlyph {
    parts: GlyphPart[]
    viewBox: string
}

const DEFAULT_ICON_VIEWBOX = '0 0 24 24'
// Elements that paint nothing or only group others, so a glyph can pass through them.
const PASS_THROUGH_TAGS = new Set(['g', 'defs', 'clippath', 'title', 'desc'])

/**
 * The fill paths of a rendered icon, so the desktop can draw it as a glass glyph. Reads the DOM
 * rather than the React tree, so it works for any icon, whatever the build did to its name.
 * Returns null when the icon paints anything besides paths, so the caller can show it as is.
 */
export function glyphFromSvg(svg: Element | null): IconGlyph | null {
    if (!svg || svg.tagName.toLowerCase() !== 'svg') {
        return null
    }
    const parts: GlyphPart[] = []
    for (const element of Array.from(svg.querySelectorAll('*'))) {
        const tag = element.tagName.toLowerCase()
        const insideDefs = !!element.parentElement?.closest('defs, clipPath, clippath')
        if (PASS_THROUGH_TAGS.has(tag) || insideDefs) {
            continue
        }
        const d = element.getAttribute('d')
        if (tag !== 'path' || !d) {
            return null
        }
        parts.push({ d, fillRule: element.getAttribute('fill-rule') === 'evenodd' ? 'evenodd' : 'nonzero' })
    }
    return parts.length ? { parts, viewBox: svg.getAttribute('viewBox') ?? DEFAULT_ICON_VIEWBOX } : null
}
