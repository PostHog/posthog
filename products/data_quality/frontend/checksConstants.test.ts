import { dayjs } from 'lib/dayjs'

import { failingForLabel } from './checksConstants'

describe('checksConstants', () => {
    const now = dayjs('2026-08-19T12:00:00Z')

    // A red tag alone never says "since when", and the answer can be older than any page of run
    // history, so it has to come off the check rather than be derived from the runs on screen.
    it.each<[string, string, string | null, string | null, string | null]>([
        ['passing checks say nothing', 'passed', '2026-08-19T11:00:00Z', null, null],
        ['checks that never ran say nothing', '', null, null, null],
        [
            'a failing check counts from when it started failing, not from its last pass',
            'failed',
            '2026-08-16T12:00:00Z',
            '2026-08-19T11:55:00Z',
            'for 5 minutes',
        ],
        ['an erroring check counts too', 'errored', null, '2026-08-19T09:00:00Z', 'for 3 hours'],
        ['a check with no pass on record says so', 'failed', null, null, 'never passed'],
        [
            'a check failing since before the streak was tracked says nothing',
            'failed',
            '2026-08-16T12:00:00Z',
            null,
            null,
        ],
    ])('%s', (_case, lastStatus, lastSucceededAt, failingSince, expected) => {
        expect(
            failingForLabel(
                { last_status: lastStatus, last_succeeded_at: lastSucceededAt, failing_since: failingSince },
                now
            )
        ).toEqual(expected)
    })
})
