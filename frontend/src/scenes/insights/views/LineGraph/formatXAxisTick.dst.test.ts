// Must be set before any imports so Node picks up the non-UTC timezone
process.env.TZ = 'America/New_York'

import { createXAxisTickCallback } from './formatXAxisTick'

describe('createXAxisTickCallback (DST)', () => {
    it('does not shift dates around US DST spring-forward transition', () => {
        // US DST spring-forward is March 8, 2026. When the browser timezone
        // differs from the project timezone, dayjs.tz() can mis-parse dates
        // near the transition, causing e.g. Mar 8 to show as Mar 7.
        const callback = createXAxisTickCallback({
            interval: 'day',
            allDays: ['2026-03-07', '2026-03-08', '2026-03-09'],
            timezone: 'US/Pacific',
        })
        expect(callback('ignored', 0)).toBe('Mar 7')
        expect(callback('ignored', 1)).toBe('Mar 8')
        expect(callback('ignored', 2)).toBe('Mar 9')
    })
})
