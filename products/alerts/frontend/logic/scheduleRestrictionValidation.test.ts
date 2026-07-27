import {
    allowedLocalMinuteIntervalsForQuietHours,
    blockedAndAllowedMinuteIntervalsForQuietHours,
    complementMinuteIntervals,
    findQuietHoursIssues,
    parseHHMMStrict,
    quietHoursFormError,
} from './scheduleRestrictionValidation'

describe('scheduleRestrictionValidation', () => {
    describe('parseHHMMStrict', () => {
        it('accepts valid 24-hour times', () => {
            expect(parseHHMMStrict('00:00')).toBe(0)
            expect(parseHHMMStrict('23:59')).toBe(23 * 60 + 59)
            expect(parseHHMMStrict('9:05')).toBe(9 * 60 + 5)
        })

        it('rejects seconds and malformed strings', () => {
            expect(parseHHMMStrict('12:00:00')).toBeNull()
            expect(parseHHMMStrict('')).toBeNull()
            expect(parseHHMMStrict('25:00')).toBeNull()
        })
    })

    describe('findQuietHoursIssues', () => {
        it('flags equal start and end', () => {
            const issue = findQuietHoursIssues([{ start: '10:00', end: '10:00' }])
            expect(issue?.kind).toBe('row')
            expect(issue?.message).toContain('differ')
        })

        it('flags merged coverage of full local day', () => {
            const issue = findQuietHoursIssues([
                { start: '00:00', end: '12:00' },
                { start: '12:00', end: '00:00' },
            ])
            expect(issue?.kind).toBe('form')
            expect(issue?.message).toContain('at least one time')
        })

        it('allows overnight wrap when day remains partially open', () => {
            expect(findQuietHoursIssues([{ start: '22:00', end: '07:00' }])).toBeNull()
        })

        it('flags same-day window shorter than 30 minutes', () => {
            const issue = findQuietHoursIssues([{ start: '10:00', end: '10:29' }])
            expect(issue?.kind).toBe('row')
            expect(issue?.message).toContain('30 minutes')
        })

        it('allows same-day window of exactly 30 minutes', () => {
            expect(findQuietHoursIssues([{ start: '10:00', end: '10:30' }])).toBeNull()
        })

        it('allows identical rows (API merges duplicates)', () => {
            expect(
                findQuietHoursIssues([
                    { start: '10:00', end: '11:00' },
                    { start: '10:00', end: '11:00' },
                ])
            ).toBeNull()
        })

        it('allows duplicate overnight rows', () => {
            expect(
                findQuietHoursIssues([
                    { start: '22:00', end: '07:00' },
                    { start: '22:00', end: '07:00' },
                ])
            ).toBeNull()
        })

        it('allows same window with different HH:MM formatting', () => {
            expect(
                findQuietHoursIssues([
                    { start: '09:00', end: '10:00' },
                    { start: '9:00', end: '10:00' },
                ])
            ).toBeNull()
        })
    })

    describe('complementMinuteIntervals', () => {
        it('returns full day when nothing blocked', () => {
            expect(complementMinuteIntervals([])).toEqual([[0, 1440]])
        })

        it('returns gap between two blocked bands overnight preset shape', () => {
            const merged = [
                [0, 7 * 60],
                [22 * 60, 1440],
            ] as [number, number][]
            expect(complementMinuteIntervals(merged)).toEqual([[7 * 60, 22 * 60]])
        })
    })

    describe('allowedLocalMinuteIntervalsForQuietHours', () => {
        it('matches complement of merged quiet for overnight preset', () => {
            expect(allowedLocalMinuteIntervalsForQuietHours([{ start: '22:00', end: '07:00' }])).toEqual([
                [7 * 60, 22 * 60],
            ])
        })

        it('returns null when windows are invalid', () => {
            expect(allowedLocalMinuteIntervalsForQuietHours([{ start: '10:00', end: '10:00' }])).toBeNull()
        })
    })

    describe('blockedAndAllowedMinuteIntervalsForQuietHours', () => {
        it('returns paired blocked and allowed for overnight preset', () => {
            const windows = [{ start: '22:00', end: '07:00' }]
            const both = blockedAndAllowedMinuteIntervalsForQuietHours(windows)
            expect(both?.blocked).toEqual([
                [0, 7 * 60],
                [22 * 60, 1440],
            ])
            expect(both?.allowed).toEqual([[7 * 60, 22 * 60]])
        })

        it('returns null when invalid', () => {
            expect(blockedAndAllowedMinuteIntervalsForQuietHours([{ start: '10:00', end: '10:00' }])).toBeNull()
        })
    })

    describe('quietHoursFormError', () => {
        it('returns undefined when quiet hours are off or empty', () => {
            expect(quietHoursFormError(undefined)).toBeUndefined()
            expect(quietHoursFormError(null)).toBeUndefined()
            expect(quietHoursFormError({ blocked_windows: [] })).toBeUndefined()
        })

        it('returns the same message as findQuietHoursIssues for invalid windows', () => {
            const windows = [{ start: '10:00', end: '10:00' }]
            const fromFind = findQuietHoursIssues(windows)
            expect(quietHoursFormError({ blocked_windows: windows })).toBe(fromFind?.message)
        })

        it('returns max windows message when over limit', () => {
            const windows = Array.from({ length: 6 }, (_, i) => ({
                start: `${String(i).padStart(2, '0')}:00`,
                end: `${String(i).padStart(2, '0')}:30`,
            }))
            const err = quietHoursFormError({ blocked_windows: windows })
            expect(err).toContain('At most')
        })
    })
})
