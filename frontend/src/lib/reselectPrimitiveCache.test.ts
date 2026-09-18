import { weakMapMemoize } from 'reselect'

// Guards patches/reselect@5.2.0.patch: kea builds every selector on weakMapMemoize, which keeps
// primitive arguments in a plain Map. Unpatched, a long-lived tab grows that Map until V8 refuses
// a larger one and the app throws "Map maximum size exceeded".
describe('reselect primitive cache bound', () => {
    it('stops growing once enough distinct primitives arrive, and still memoizes repeats', () => {
        let calls = 0
        const double = weakMapMemoize((n: number) => {
            calls++
            return n * 2
        })

        expect(double(1)).toBe(2)
        expect(double(1)).toBe(2)
        expect(calls).toBe(1)

        for (let n = 0; n < 2000; n++) {
            double(n)
        }
        const callsBeforeReuse = calls

        expect(double(1)).toBe(2)
        expect(calls).toBe(callsBeforeReuse + 1)
    })
})
