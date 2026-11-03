import { dayjs } from 'lib/dayjs'

import { pulseWhy } from './todayPulseFacts'
import { makePulseMetric } from './todayTestFixtures'

describe('todayPulseFacts', () => {
    const today = dayjs('2026-09-30T10:00:00')

    it.each([
        [
            'an insight opened on several days',
            { reason: 'routine', opened_days: 5, last_opened: '2026-09-29' },
            'You opened this insight on 5 of the last 14 days, most recently yesterday.',
        ],
        [
            'an insight opened once',
            { reason: 'routine', opened_days: 1, last_opened: '2026-09-21' },
            'You last opened this insight on Sep 21.',
        ],
        [
            'a dashboard tile opened today',
            { reason: 'dashboard', dashboard_name: 'Growth', opened_days: 9, last_opened: '2026-09-30' },
            'You opened the Growth dashboard on 9 of the last 14 days, most recently today. This is the first chart on that dashboard.',
        ],
        [
            'a key metric',
            { reason: 'key_metric', opened_days: null, last_opened: null },
            'It is a key metric for this project, set in Customer analytics.',
        ],
        ['a metric computed before reasons existed', { reason: null }, null],
    ] as const)('explains %s', (_name, overrides, expected) => {
        expect(pulseWhy(makePulseMetric(overrides), today)).toBe(expected)
    })
})
