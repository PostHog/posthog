/**
 * Comment and emoji ticks are wide glyphs centred on their timestamp, so two of them recorded
 * close together render on top of each other and become unreadable.
 */
export interface SeekbarGlyph {
    index: number
    /** Horizontal centre of the glyph, as a percentage (0-100) of the seekbar width. */
    position: number
    /** Rendered width of the glyph in pixels. */
    widthPx: number
}

export const GLYPH_GAP_PX = 2

/** Offsets in pixels keyed by tick index. A glyph that needs no moving is absent from the map. */
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

        let left: number = previousRight === null ? naturalLeft : Math.max(naturalLeft, previousRight + gapPx)
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
