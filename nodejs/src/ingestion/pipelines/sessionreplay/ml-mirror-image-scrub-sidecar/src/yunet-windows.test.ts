import { FACE_MAX_WINDOWS } from './scale-plan.ts'
import { detectionWindowsForTest, faceInputSides, mergePasses, passesForWindow } from './yunet.ts'

describe('detectionWindows', () => {
    it.each([
        [640, [640]],
        [1536, [1536, 640]],
    ])('keeps the measured 640 face pass when the input is %p', (inputSide, sides) => {
        // YuNet's floors were measured at 640; a larger input alone could miss a close-up face it was never checked on.
        expect(faceInputSides(inputSide)).toEqual(sides)
    })

    it.each([
        ['a window within 640 runs once', 400, 300, [1536]],
        ['a window of exactly 640 runs once', 640, 360, [1536]],
        ['a window the 640 pass shrinks runs at each', 1280, 720, [1536, 640]],
    ])('%s', (_case, width, height, sides) => {
        expect(passesForWindow({ left: 0, top: 0, width, height }, [1536, 640])).toEqual(sides)
    })

    it('keeps a face box from one pass that a tighter, higher-scoring box from another pass overlaps', () => {
        const tight = { left: 110, top: 110, width: 80, height: 80 }
        const wide = { left: 100, top: 100, width: 120, height: 120 }
        expect(mergePasses([[{ b: tight, s: 0.95 }], [{ b: wide, s: 0.75 }]])).toEqual([tight, wide])
        expect(
            mergePasses([
                [
                    { b: tight, s: 0.95 },
                    { b: wide, s: 0.75 },
                ],
            ])
        ).toEqual([tight])
    })

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
            // These become sharp crop rectangles, which reject fractions. A fractional window is a
            // 500 on every image of that shape, which the consumer retries and then replays as a
            // failed batch, so it has to be caught here rather than in production.
            expect(Number.isInteger(w.left)).toBe(true)
            expect(Number.isInteger(w.top)).toBe(true)
            expect(Number.isInteger(w.width)).toBe(true)
            expect(Number.isInteger(w.height)).toBe(true)
            expect(w.left).toBeGreaterThanOrEqual(0)
            expect(w.top).toBeGreaterThanOrEqual(0)
            expect(w.left + w.width).toBeLessThanOrEqual(W)
            expect(w.top + w.height).toBeLessThanOrEqual(H)
        }
    })

    it.each([
        ['a moderately long banner', 8000, 60],
        ['a degenerate strip', 88_590, 8],
        ['an extreme strip', 280_149, 2],
    ])('bounds how many inferences %s costs', (_case, W, H) => {
        // The window count grows with the aspect ratio, which the frame's AREA budget does not bound:
        // a 400000x4 source asked for 28,015 face inferences from about 100 KB of PNG, which pins a
        // worker for minutes and trips its deadline. Past the cap the windows widen rather than
        // multiply, so the frame is still covered end to end.
        const windows = detectionWindowsForTest(W, H)

        expect(windows.length).toBeLessThanOrEqual(FACE_MAX_WINDOWS + 1)
        expect(Math.max(...windows.map((w) => Math.max(w.left + w.width, w.top + w.height)))).toBe(Math.max(W, H))
    })

    it('covers the whole long side across its windows', () => {
        // Overlap is deliberate (one short-side of it), so a face cannot straddle two windows and be
        // missed by both. Gaps would be a silent miss in the same way.
        const windows = detectionWindowsForTest(2400, 300)

        expect(Math.min(...windows.map((w) => w.left))).toBe(0)
        expect(Math.max(...windows.map((w) => w.left + w.width))).toBe(2400)
    })
})
