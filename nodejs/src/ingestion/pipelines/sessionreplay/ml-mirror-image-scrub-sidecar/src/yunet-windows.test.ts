import { detectionWindowsForTest } from './yunet.ts'

describe('detectionWindows', () => {
    // A window starting off the edge is not an error anywhere downstream: face boxes are translated
    // by its offset, so they land at negative coordinates and are clamped away. Face redaction goes
    // silently off for the whole shape class, which is why this needs a test rather than a reader
    // noticing. Aspect ratios between MAX_ASPECT and TILE_ASPECT are the gap: the frame is longer
    // than a single pass allows but SHORTER than one tile.
    it.each([
        ['just over the tiling threshold', 901, 300],
        ['a 4:1 banner', 1200, 300],
        ['a 4:1 banner rotated', 300, 1200],
        ['exactly at the tile aspect', 1800, 300],
        ['beyond the tile aspect', 2400, 300],
        ['an ordinary frame', 1920, 1080],
    ])('keeps every window inside %s', (_case, W, H) => {
        const windows = detectionWindowsForTest(W, H)

        expect(windows.length).toBeGreaterThan(0)
        for (const w of windows) {
            expect(w.left).toBeGreaterThanOrEqual(0)
            expect(w.top).toBeGreaterThanOrEqual(0)
            expect(w.left + w.width).toBeLessThanOrEqual(W)
            expect(w.top + w.height).toBeLessThanOrEqual(H)
        }
    })

    it('covers the whole long side across its windows', () => {
        // Overlap is deliberate (one short-side of it), so a face cannot straddle two windows and be
        // missed by both. Gaps would be a silent miss in the same way.
        const windows = detectionWindowsForTest(2400, 300)

        expect(Math.min(...windows.map((w) => w.left))).toBe(0)
        expect(Math.max(...windows.map((w) => w.left + w.width))).toBe(2400)
    })
})
