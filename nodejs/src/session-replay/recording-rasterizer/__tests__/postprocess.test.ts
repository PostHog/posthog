import { computeVideoTimestamps } from '../postprocess'
import { InactivityPeriod } from '../types'

describe('computeVideoTimestamps', () => {
    it('maps active periods to cumulative video time', () => {
        const periods: InactivityPeriod[] = [
            { ts_from_s: 0, ts_to_s: 10, active: true },
            { ts_from_s: 10, ts_to_s: 20, active: true },
        ]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(10)
        expect(result[1].recording_ts_from_s).toBe(10)
        expect(result[1].recording_ts_to_s).toBe(20)
    })

    it('inactive periods get zero video duration', () => {
        const periods: InactivityPeriod[] = [
            { ts_from_s: 0, ts_to_s: 10, active: true },
            { ts_from_s: 10, ts_to_s: 50, active: false },
            { ts_from_s: 50, ts_to_s: 60, active: true },
        ]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(10)
        // Inactive period points to same position
        expect(result[1].recording_ts_from_s).toBe(10)
        expect(result[1].recording_ts_to_s).toBe(10)
        // Next active period starts where the last active ended
        expect(result[2].recording_ts_from_s).toBe(10)
        expect(result[2].recording_ts_to_s).toBe(20)
    })

    it('handles empty input', () => {
        expect(computeVideoTimestamps([])).toEqual([])
    })

    it('handles single active period', () => {
        const periods: InactivityPeriod[] = [{ ts_from_s: 0, ts_to_s: 30, active: true }]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(30)
    })

    it('handles period with null ts_to_s', () => {
        const periods: InactivityPeriod[] = [{ ts_from_s: 0, ts_to_s: null, active: true }]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(0) // duration is 0 when ts_to_s is null
    })

    it('handles multiple inactive gaps', () => {
        const periods: InactivityPeriod[] = [
            { ts_from_s: 0, ts_to_s: 5, active: true },
            { ts_from_s: 5, ts_to_s: 100, active: false },
            { ts_from_s: 100, ts_to_s: 110, active: true },
            { ts_from_s: 110, ts_to_s: 200, active: false },
            { ts_from_s: 200, ts_to_s: 205, active: true },
        ]

        const result = computeVideoTimestamps(periods)

        // 5s active + 10s active + 5s active = 20s total video
        expect(result[0]).toMatchObject({ recording_ts_from_s: 0, recording_ts_to_s: 5 })
        expect(result[1]).toMatchObject({ recording_ts_from_s: 5, recording_ts_to_s: 5 })
        expect(result[2]).toMatchObject({ recording_ts_from_s: 5, recording_ts_to_s: 15 })
        expect(result[3]).toMatchObject({ recording_ts_from_s: 15, recording_ts_to_s: 15 })
        expect(result[4]).toMatchObject({ recording_ts_from_s: 15, recording_ts_to_s: 20 })
    })

    it('preserves original fields', () => {
        const periods: InactivityPeriod[] = [{ ts_from_s: 5, ts_to_s: 10, active: true }]

        const result = computeVideoTimestamps(periods)

        expect(result[0].ts_from_s).toBe(5)
        expect(result[0].ts_to_s).toBe(10)
        expect(result[0].active).toBe(true)
    })
})
