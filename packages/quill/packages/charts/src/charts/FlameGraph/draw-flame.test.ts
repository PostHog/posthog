import { createLabelFitter } from './draw-flame'

const fakeCtx = {
    measureText: (text: string) => ({ width: Array.from(text).length * 7 }),
} as unknown as CanvasRenderingContext2D

describe('createLabelFitter', () => {
    it.each([
        { text: 'United Kingdom', available: 70, expected: 'United Ki…' },
        { text: 'Chrome', available: 8, expected: '' },
        { text: 'Éaaaaaaa', available: 56, expected: 'Éaaaaaaa' },
    ])('fits "$text" into $available px', ({ text, available, expected }) => {
        const label = createLabelFitter().fit(fakeCtx, text, available)
        expect(label).toBe(expected)
        expect(fakeCtx.measureText(label).width).toBeLessThanOrEqual(available)
    })
})
