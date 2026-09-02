import { isStoredCrashFirst, toDisplayOrderFrames } from './displayOrder'
import { ErrorTrackingStackFrame } from './types'

describe('toDisplayOrderFrames', () => {
    const frame = (fn: string): ErrorTrackingStackFrame =>
        ({ raw_id: fn, mangled_name: fn, in_app: true, resolved: false, lang: 'javascript' }) as ErrorTrackingStackFrame

    it('shows the crash site first from canonical bottom-up storage', () => {
        const stored = [frame('main'), frame('handler'), frame('crash')]
        const display = toDisplayOrderFrames(stored)
        expect(display.map((f) => f.raw_id)).toEqual(['crash', 'handler', 'main'])
        // stored input is not mutated
        expect(stored.map((f) => f.raw_id)).toEqual(['main', 'handler', 'crash'])
    })

    it('keeps pre-normalization crash-first storage as-is', () => {
        const stored = [frame('crash'), frame('handler'), frame('main')]
        const display = toDisplayOrderFrames(stored, true)
        expect(display.map((f) => f.raw_id)).toEqual(['crash', 'handler', 'main'])
        expect(display).not.toBe(stored)
    })
})

describe('isStoredCrashFirst', () => {
    it.each([
        ['posthog-go', '2026-07-01T00:00:00Z', true],
        ['posthog-go', '2026-07-15T00:00:00Z', false],
        // events after the deploy moment on rollout day are stored canonical
        ['posthog-go', '2026-07-09T20:00:00Z', false],
        ['posthog-go', '2026-07-09T12:00:00Z', true],
        // API timestamp forms that do not sort lexically against the cutoff
        ['posthog-go', '2026-07-09T16:10:00.500000+00:00', false],
        ['posthog-go', '2026-07-09T12:00:00.123456+00:00', true],
        ['posthog-go', 'not-a-date', false],
        ['posthog-python', '2026-07-01T00:00:00Z', false], // python frames were always bottom-up
        ['web', '2026-07-01T00:00:00Z', false],
        [undefined, '2026-07-01T00:00:00Z', false],
        ['posthog-android', undefined, false],
    ])('%s @ %s -> %s', (lib, timestamp, expected) => {
        expect(isStoredCrashFirst(lib as string | undefined, timestamp as string | undefined)).toBe(expected)
    })
})
