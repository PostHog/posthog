import { computePlayerScale } from './computePlayerScale'

describe('computePlayerScale', () => {
    it.each([
        {
            name: 'normal landscape fit (limited by width)',
            replay: { width: 1920, height: 1080 },
            parent: { width: 960, height: 800 },
            expected: 0.5,
        },
        {
            name: 'normal portrait fit (limited by height)',
            replay: { width: 1000, height: 2000 },
            parent: { width: 800, height: 800 },
            expected: 0.4,
        },
        {
            name: 'caps below identity to dodge the Chrome compositing bug',
            replay: { width: 100, height: 100 },
            parent: { width: 500, height: 500 },
            expected: 0.999,
        },
    ])('returns the expected scale: $name', ({ replay, parent, expected }) => {
        const scale = computePlayerScale(replay, parent)
        expect(scale).toBeCloseTo(expected, 5)
    })

    // These are the cases that produced the 2x-fast-forward white screen — the rrweb resize
    // handler used to commit `scale(0)` (or NaN) when either side was zero, which left the
    // wrapper invisible until something else triggered a recalc. The guard must return null
    // so the caller leaves the previous valid transform in place.
    it.each([
        { name: 'undefined replay dimensions', replay: undefined, parent: { width: 800, height: 600 } },
        { name: 'undefined parent dimensions', replay: { width: 1024, height: 768 }, parent: undefined },
        { name: 'zero parent width', replay: { width: 1024, height: 768 }, parent: { width: 0, height: 600 } },
        { name: 'zero parent height', replay: { width: 1024, height: 768 }, parent: { width: 800, height: 0 } },
        { name: 'zero replay width', replay: { width: 0, height: 768 }, parent: { width: 800, height: 600 } },
        { name: 'zero replay height', replay: { width: 1024, height: 0 }, parent: { width: 800, height: 600 } },
        { name: 'negative parent width', replay: { width: 1024, height: 768 }, parent: { width: -10, height: 600 } },
        { name: 'NaN replay width', replay: { width: NaN, height: 768 }, parent: { width: 800, height: 600 } },
        { name: 'NaN parent height', replay: { width: 1024, height: 768 }, parent: { width: 800, height: NaN } },
    ])('returns null for degenerate inputs: $name', ({ replay, parent }) => {
        expect(computePlayerScale(replay, parent)).toBeNull()
    })
})
