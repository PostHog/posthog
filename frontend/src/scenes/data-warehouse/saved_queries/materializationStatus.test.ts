import { estimateNextRunAt, syncFrequencyPhrase } from './materializationStatus'

describe('materializationStatus', () => {
    it.each([
        ['15min', '2026-07-30T12:00:00Z', '2026-07-30T12:15:00Z'],
        ['6hour', '2026-07-30T12:00:00Z', '2026-07-30T18:00:00Z'],
        ['24hour', '2026-07-30T12:00:00Z', '2026-07-31T12:00:00Z'],
        ['30day', '2026-07-01T00:00:00Z', '2026-07-31T00:00:00Z'],
    ])('estimateNextRunAt adds the %s interval to the last run', (frequency, lastRunAt, expected) => {
        expect(estimateNextRunAt(lastRunAt, frequency)?.toISOString()).toEqual(new Date(expected).toISOString())
    })

    it.each([
        [null, '2026-07-30T12:00:00Z'],
        ['never', '2026-07-30T12:00:00Z'],
        ['not-a-frequency', '2026-07-30T12:00:00Z'],
        ['6hour', null],
        ['6hour', 'garbage-date'],
    ])('estimateNextRunAt returns null for frequency=%s lastRunAt=%s', (frequency, lastRunAt) => {
        expect(estimateNextRunAt(lastRunAt, frequency)).toBeNull()
    })

    it.each([
        ['6hour', 'every 6 hours'],
        ['24hour', 'daily'],
        ['never', null],
        [null, null],
        ['unknown', null],
    ])('syncFrequencyPhrase(%s) -> %s', (frequency, expected) => {
        expect(syncFrequencyPhrase(frequency)).toEqual(expected)
    })
})
