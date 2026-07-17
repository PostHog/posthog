import { monotonicNow } from './time'

describe('monotonicNow', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('uses performance.now() when it is available', () => {
        // jsdom exposes `performance` via a getter, so spy on the getter rather than replacing it.
        jest.spyOn(globalThis, 'performance', 'get').mockReturnValue({ now: () => 1234.5 } as unknown as Performance)
        expect(monotonicNow()).toBe(1234.5)
    })

    it('falls back to Date.now() without throwing when performance is absent', () => {
        // The jsdom worker that flaked dropped the global `performance`; a bare performance.now()
        // there throws ReferenceError mid-render and trips the chart's error boundary.
        jest.spyOn(globalThis, 'performance', 'get').mockReturnValue(undefined as unknown as Performance)
        const before = Date.now()
        expect(monotonicNow()).toBeGreaterThanOrEqual(before)
    })
})
