import { LabelFitter } from './draw-flame'

// Every glyph 7px wide except wide ones, so the expected cuts are easy to read.
const fakeCtx = {
    measureText: (text: string) => ({ width: Array.from(text).reduce((w, ch) => w + (ch === 'W' ? 14 : 7), 0) }),
} as unknown as CanvasRenderingContext2D

describe('LabelFitter', () => {
    // Non-ASCII labels take the measured path, so uneven glyph widths matter there.
    it.each([
        { text: 'United Kingdom', available: 70, expected: 'United Ki…' },
        { text: 'Chrome', available: 8, expected: '' },
        { text: 'ÉWWWWW', available: 50, expected: 'ÉWW…' },
        { text: 'ÉWWaaaa', available: 50, expected: 'ÉWWa…' },
        { text: 'Éaaaaaaa', available: 56, expected: 'Éaaaaaaa' },
    ])('fits "$text" into $available px', ({ text, available, expected }) => {
        const label = new LabelFitter().fit(fakeCtx, text, available)
        expect(label).toBe(expected)
        expect(fakeCtx.measureText(label).width).toBeLessThanOrEqual(available)
    })
})
