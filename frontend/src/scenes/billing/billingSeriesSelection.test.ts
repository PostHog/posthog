import { billingSeriesKey, hiddenSeriesAfterToggleAll } from './billingSeriesSelection'

describe('billingSeriesSelection', () => {
    describe('billingSeriesKey', () => {
        it.each([
            ['a usage type', 'event_count_in_period', '"event_count_in_period"'],
            ['a usage type and project', ['event_count_in_period', '134'], '["event_count_in_period","134"]'],
            ['no breakdown', null, 'Total'],
            ['an empty breakdown value', '', 'Total'],
            ['an empty breakdown pair', [], 'Total'],
        ])('keys a series with %s', (_name, breakdown_value, expected) => {
            expect(billingSeriesKey({ label: 'Total', breakdown_value })).toBe(expected)
        })

        it('tells two projects of the same product apart', () => {
            const a = billingSeriesKey({ label: 'Project 134', breakdown_value: ['events', '134'] })
            const b = billingSeriesKey({ label: 'Project 135', breakdown_value: ['events', '135'] })
            expect(a).not.toBe(b)
        })
    })

    describe('hiddenSeriesAfterToggleAll', () => {
        const series = [
            { key: 'a', data: [1] },
            { key: 'b', data: [2] },
            { key: 'empty', data: [0] },
        ]

        it('keeps a hidden key that is not in the current series when hiding all', () => {
            expect(hiddenSeriesAfterToggleAll(series, false, ['gone'])).toEqual(['gone', 'a', 'b', 'empty'])
        })

        it('leaves empty series alone when they are already excluded', () => {
            expect(hiddenSeriesAfterToggleAll(series, true, [])).toEqual(['a', 'b'])
        })

        it('shows everything again once any series is hidden', () => {
            expect(hiddenSeriesAfterToggleAll(series, false, ['a'])).toEqual([])
        })
    })
})
