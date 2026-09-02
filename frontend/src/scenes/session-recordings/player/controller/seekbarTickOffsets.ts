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
    const naturalLefts = sorted.map((glyph) => (glyph.position / 100) * containerWidthPx - glyph.widthPx / 2)
    const lefts: number[] = []

    // left to right, pushing each glyph clear of the one before it
    for (let i = 0; i < sorted.length; i++) {
        const earliest = i === 0 ? 0 : lefts[i - 1] + sorted[i - 1].widthPx + gapPx
        lefts.push(Math.max(naturalLefts[i], earliest, 0))
    }

    // Right to left, so a run that would extend past the end of the seekbar gets packed back towards
    // the start. Without this every glyph in the run pins to the same maximum left edge and they
    // overlap again, which is the problem this whole module exists to avoid.
    for (let i = sorted.length - 1; i >= 0; i--) {
        const rightBound = i === sorted.length - 1 ? containerWidthPx : lefts[i + 1] - gapPx
        lefts[i] = Math.min(lefts[i], rightBound - sorted[i].widthPx)
    }

    sorted.forEach((glyph, i) => {
        // A run wider than the whole seekbar can't be separated, so keep it on screen and let it
        // overlap rather than pushing glyphs off the left edge where they'd be invisible.
        const left = Math.max(0, lefts[i])
        const offset = left - naturalLefts[i]
        if (offset !== 0) {
            offsets.set(glyph.index, offset)
        }
    })

    return offsets
}
