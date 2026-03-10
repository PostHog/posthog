// This test must be run with TZ=America/New_York to reproduce the DST bug.
// Use: pnpm --filter=@posthog/frontend test:tz
// It is excluded from the default jest run (which forces TZ=UTC).
import { createXAxisTickCallback } from './formatXAxisTick'

it('does not shift dates around US DST spring-forward transition', () => {
    // Sanity check: if TZ is UTC both code paths produce the same result,
    // so the test would pass even with the buggy code.
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).not.toBe('UTC')

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
