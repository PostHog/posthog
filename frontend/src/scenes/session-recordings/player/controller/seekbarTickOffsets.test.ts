import {
    GLYPH_GAP_PX,
    SeekbarGlyph,
    resolveOverlappingGlyphs,
} from 'scenes/session-recordings/player/controller/seekbarTickOffsets'

const CONTAINER_WIDTH = 600

function leftEdges(glyphs: SeekbarGlyph[], containerWidth: number = CONTAINER_WIDTH): number[] {
    const offsets = resolveOverlappingGlyphs(glyphs, containerWidth)
    return glyphs.map((glyph) => {
        const naturalLeft = (glyph.position / 100) * containerWidth - glyph.widthPx / 2
        return naturalLeft + (offsets.get(glyph.index) ?? 0)
    })
}

function glyph(index: number, position: number, widthPx: number = 12): SeekbarGlyph {
    return { index, position, widthPx }
}

describe('resolveOverlappingGlyphs', () => {
    it('separates a comment and an emoji recorded at the same moment', () => {
        const glyphs = [glyph(0, 50, 12), glyph(1, 50, 16)]

        const edges = leftEdges(glyphs)

        const [first, second] = edges[0] <= edges[1] ? [0, 1] : [1, 0]
        expect(edges[second]).toBeGreaterThanOrEqual(edges[first] + glyphs[first].widthPx + GLYPH_GAP_PX)
    })

    it('keeps every glyph inside the seekbar when they pile up at the end', () => {
        const glyphs = [glyph(0, 99.5), glyph(1, 99.7), glyph(2, 100)]

        const edges = leftEdges(glyphs)

        edges.forEach((left, i) => {
            expect(left).toBeGreaterThanOrEqual(0)
            expect(left + glyphs[i].widthPx).toBeLessThanOrEqual(CONTAINER_WIDTH)
        })
    })

    it('resolves collisions by position, not input order', () => {
        const glyphs = [glyph(0, 60), glyph(1, 20), glyph(2, 20.5)]

        const offsets = resolveOverlappingGlyphs(glyphs, CONTAINER_WIDTH)

        // the isolated glyph at 60% is untouched, the pair at ~20% is pushed apart
        expect(offsets.has(0)).toBe(false)
        const edges = leftEdges(glyphs)
        expect(Math.abs(edges[2] - edges[1])).toBeGreaterThanOrEqual(12 + GLYPH_GAP_PX)
    })

    it.each([
        ['a single glyph', [glyph(0, 50)], CONTAINER_WIDTH],
        ['glyphs that are far apart', [glyph(0, 10), glyph(1, 50), glyph(2, 90)], CONTAINER_WIDTH],
        ['an unmeasured container', [glyph(0, 50), glyph(1, 50)], 0],
    ])('leaves %s alone', (_name, glyphs, containerWidth) => {
        expect(resolveOverlappingGlyphs(glyphs as SeekbarGlyph[], containerWidth as number).size).toBe(0)
    })
})
