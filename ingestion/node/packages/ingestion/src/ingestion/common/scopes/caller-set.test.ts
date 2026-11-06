import { CallerSet } from './caller-set'

describe('CallerSet', () => {
    it('tracks the number of active callers', () => {
        const set = new CallerSet()
        expect(set.size()).toBe(0)

        const releaseA = set.register()
        const releaseB = set.register()
        expect(set.size()).toBe(2)

        releaseA()
        expect(set.size()).toBe(1)

        releaseB()
        expect(set.size()).toBe(0)
    })

    it('returns true only on the first release of a caller', () => {
        const set = new CallerSet()
        const release = set.register()

        expect(release()).toBe(true)
        expect(release()).toBe(false)
        expect(release()).toBe(false)
    })

    it('does not double-count a single-shot release against size', () => {
        const set = new CallerSet()
        const release = set.register()
        set.register()

        release()
        release()

        expect(set.size()).toBe(1)
    })
})
