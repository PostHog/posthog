/**
 * Comment and emoji ticks are wide glyphs centred on their timestamp, so ticks that sit close
 * together in the recording render on top of each other and become unreadable. Nudging them
 * sideways keeps every glyph visible and clickable while staying near its real position.
 */
export interface SeekbarGlyph {
    /** Index of the tick in the rendered list, used to look the offset back up. */
    index: number
    /** Horizontal centre of the glyph, as a percentage (0-100) of the seekbar width. */
    position: number
    /** Rendered width of the glyph in pixels. Mirrors --emoji-width / --comment-width in Seekbar.scss. */
    widthPx: number
}

export const GLYPH_GAP_PX = 2

/**
 * Returns the horizontal offset in pixels to apply to each glyph, keyed by tick index.
 * Glyphs that don't need moving are left out.
 */
export function resolveOverlappingGlyphs(
    glyphs: SeekbarGlyph[],
    containerWidthPx: number,
    gapPx: number = GLYPH_GAP_PX
): Map<number, number> {
    const offsets = new Map<number, number>()
    if (containerWidthPx <= 0 || glyphs.length < 2) {
        return offsets
    }

    const sorted = [...glyphs].sort((a, b) => a.position - b.position)

    let previousRight: number | null = null
    for (const glyph of sorted) {
        const centre = (glyph.position / 100) * containerWidthPx
        const naturalLeft = centre - glyph.widthPx / 2

        let left = previousRight === null ? naturalLeft : Math.max(naturalLeft, previousRight + gapPx)
        // never push a glyph out of the seekbar, even if that means it still overlaps
        left = Math.min(left, containerWidthPx - glyph.widthPx)

        const offset = left - naturalLeft
        if (offset !== 0) {
            offsets.set(glyph.index, offset)
        }
        previousRight = left + glyph.widthPx
    }

    return offsets
}
