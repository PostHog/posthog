import { expandToNextDateRangePreset, zoomDateRange } from './zoom-utils'

describe('zoomDateRange', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00.000Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('relative date ranges', () => {
        it('multiplies relative date_from when date_to is not set', () => {
            const result = zoomDateRange({ date_from: '-1h', date_to: null }, 2)
            expect(result).toEqual({ date_from: '-2h', date_to: null })
        })

        it('handles different relative units', () => {
            expect(zoomDateRange({ date_from: '-30m', date_to: null }, 2)).toEqual({
                date_from: '-60m',
                date_to: null,
            })
            expect(zoomDateRange({ date_from: '-7d', date_to: null }, 2)).toEqual({
                date_from: '-14d',
                date_to: null,
            })
        })

        it('multiplies minute presets while preserving the live-tail (uppercase M)', () => {
            // PostHog's minute presets use uppercase M (e.g. -5M); these must keep date_to: null
            expect(zoomDateRange({ date_from: '-5M', date_to: null }, 2)).toEqual({
                date_from: '-10M',
                date_to: null,
            })
            expect(zoomDateRange({ date_from: '-30M', date_to: null }, 0.5)).toEqual({
                date_from: '-15M',
                date_to: null,
            })
        })

        it('rounds fractional results to a whole unit so they stay valid relative expressions', () => {
            // -5M × 0.5 = 2.5, which must not produce the unparseable "-2.5M"
            expect(zoomDateRange({ date_from: '-5M', date_to: null }, 0.5)).toEqual({
                date_from: '-3M',
                date_to: null,
            })
        })

        it('floors the amount at 1 so zooming in never collapses to zero', () => {
            expect(zoomDateRange({ date_from: '-1M', date_to: null }, 0.25)).toEqual({
                date_from: '-1M',
                date_to: null,
            })
        })
    })

    describe('absolute date ranges', () => {
        it('expands range symmetrically from center', () => {
            const result = zoomDateRange(
                {
                    date_from: '2024-01-15T10:00:00.000Z',
                    date_to: '2024-01-15T11:00:00.000Z',
                },
                2
            )
            // Original range: 10:00 - 11:00 (60 mins), center at 10:30
            // New range should be 60 mins on each side of center = 9:30 - 11:30
            // But 11:30 is before now (12:00), so no clamping needed
            expect(result.date_from).toContain('2024-01-15T09:30:00')
            expect(result.date_to).toContain('2024-01-15T11:30:00')
        })

        it('clamps date_to to now when expansion would exceed current time', () => {
            const result = zoomDateRange(
                {
                    date_from: '2024-01-15T11:00:00.000Z',
                    date_to: '2024-01-15T12:00:00.000Z',
                },
                2
            )
            // Original range: 11:00 - 12:00 (60 mins), center at 11:30
            // Expanded would be 10:30 - 12:30, but 12:30 is after now (12:00)
            // So date_to should be clamped to 12:00
            expect(result.date_from).toContain('2024-01-15T10:30:00')
            expect(result.date_to).toContain('2024-01-15T12:00:00')
        })

        it('handles zooming in (multiplier < 1)', () => {
            const result = zoomDateRange(
                {
                    date_from: '2024-01-15T10:00:00.000Z',
                    date_to: '2024-01-15T12:00:00.000Z',
                },
                0.5
            )
            // Original range: 10:00 - 12:00 (120 mins), center at 11:00
            // New range should be 30 mins on each side = 10:30 - 11:30
            expect(result.date_from).toContain('2024-01-15T10:30:00')
            expect(result.date_to).toContain('2024-01-15T11:30:00')
        })
    })

    describe('edge cases', () => {
        it('handles zero-duration range (same from/to) by using 1 minute minimum', () => {
            const result = zoomDateRange(
                {
                    date_from: '2024-01-15T10:30:00.000Z',
                    date_to: '2024-01-15T10:30:00.000Z',
                },
                2
            )
            // Original range: 0 mins, but we use 1 min minimum, center at 10:30:30
            // Expanded by 2x should give 1 min on each side = 10:29:30 - 10:31:30
            expect(result.date_from).toContain('2024-01-15T10:29:30')
            expect(result.date_to).toContain('2024-01-15T10:31:30')
        })

        it('handles missing date_from by defaulting to 1 hour ago', () => {
            const result = zoomDateRange({ date_from: null, date_to: null }, 2)
            // Default range: 11:00 - 12:00 (1h ago to now), center at 11:30
            // Expanded: 10:30 - 12:30, but clamped to 12:00
            expect(result.date_from).toContain('2024-01-15T10:30:00')
            expect(result.date_to).toContain('2024-01-15T12:00:00')
        })

        it('handles invalid date strings gracefully', () => {
            const result = zoomDateRange({ date_from: 'invalid', date_to: null }, 2)
            // Falls back to default range (1h ago to now), same as above
            expect(result.date_from).toContain('2024-01-15T10:30:00')
            expect(result.date_to).toContain('2024-01-15T12:00:00')
        })
    })
})

describe('expandToNextDateRangePreset', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00.000Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['-15M', '-30M'],
        ['-1h', '-3h'],
        ['-24h', '-3d'],
    ])('jumps from %s straight to the next wider preset %s', (date_from, expected) => {
        expect(expandToNextDateRangePreset({ date_from, date_to: null })).toEqual({
            date_from: expected,
            date_to: null,
        })
    })

    it('falls back to a 2x zoom when already at the widest preset', () => {
        // '-7d' is the last entry in DEFAULT_DATE_RANGE_PICKER_OPTIONS, so there's no next preset to jump to
        expect(expandToNextDateRangePreset({ date_from: '-7d', date_to: null })).toEqual(
            zoomDateRange({ date_from: '-7d', date_to: null }, 2)
        )
    })

    it('falls back to a 2x zoom for a non-preset relative range', () => {
        expect(expandToNextDateRangePreset({ date_from: '-42M', date_to: null })).toEqual(
            zoomDateRange({ date_from: '-42M', date_to: null }, 2)
        )
    })

    it('falls back to a 2x zoom for an absolute range', () => {
        const dateRange = { date_from: '2024-01-15T10:00:00.000Z', date_to: '2024-01-15T11:00:00.000Z' }
        expect(expandToNextDateRangePreset(dateRange)).toEqual(zoomDateRange(dateRange, 2))
    })
})
