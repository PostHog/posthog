import { LabelFitter } from './draw-flame'

// Every glyph 7px wide except wide ones, so the expected cuts are easy to read.
const fakeCtx = {
    measureText: (text: string) => ({ width: Array.from(text).reduce((w, ch) => w + (ch === 'W' ? 14 : 7), 0) }),
} as unknown as CanvasRenderingContext2D

describe('LabelFitter', () => {
    it.each([
        { font: 'monospace' as const, text: 'United Kingdom', available: 70, expected: 'United Ki…' },
        { font: 'sans' as const, text: 'United Kingdom', available: 70, expected: 'United Ki…' },
        { font: 'sans' as const, text: 'WWWWWW', available: 50, expected: 'WWW…' },
        { font: 'sans' as const, text: 'Chrome', available: 42, expected: 'Chrome' },
        { font: 'sans' as const, text: 'Chrome', available: 8, expected: '' },
        { font: 'sans' as const, text: 'WWWaaaa', available: 50, expected: 'WWW…' },
        { font: 'sans' as const, text: 'aaaaWWW', available: 56, expected: 'aaaaW…' },
    ])('fits "$text" into $available px with $font labels', ({ font, text, available, expected }) => {
        const label = new LabelFitter(font).fit(fakeCtx, text, available)
        expect(label).toBe(expected)
        expect(fakeCtx.measureText(label).width).toBeLessThanOrEqual(available)
    })
})
