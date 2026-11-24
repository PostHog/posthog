import { cleanup, render } from '@testing-library/react'

import { EmailOutcome, HogInvocationRow } from './hogInvocationsLogic'
import { RunStatusCell } from './RunStatusCell'

const runRow = (
    status: HogInvocationRow['status'],
    problemLogLevel: HogInvocationRow['problem_log_level'],
    emailOutcome: EmailOutcome | null
): HogInvocationRow => ({
    invocation_id: 'inv-1',
    function_kind: 'hog_flow',
    status,
    attempts: 1,
    is_retry: false,
    error_kind: '',
    error_message: '',
    scheduled_at: '2026-11-20T10:00:00Z',
    first_scheduled_at: '2026-11-20T10:00:00Z',
    started_at: '2026-11-20T10:00:00Z',
    finished_at: '2026-11-20T10:00:01Z',
    duration_ms: 1000,
    event_uuid: 'event-1',
    distinct_id: 'distinct-1',
    person_id: 'person-1',
    parent_run_id: '',
    problem_log_level: problemLogLevel,
    email_outcome: emailOutcome,
})

describe('RunStatusCell', () => {
    afterEach(cleanup)

    it.each([
        { status: 'succeeded', level: 'error', outcome: 'complained', tag: 'MARKED AS SPAM', warningIcon: false },
        { status: 'succeeded', level: null, outcome: 'complained', tag: 'MARKED AS SPAM', warningIcon: false },
        { status: 'succeeded', level: 'error', outcome: 'bounced', tag: 'EMAIL BOUNCED', warningIcon: false },
        { status: 'succeeded', level: null, outcome: 'bounced', tag: 'EMAIL BOUNCED', warningIcon: false },
        { status: 'succeeded', level: 'warn', outcome: null, tag: 'SUCCEEDED', warningIcon: true },
        { status: 'succeeded', level: null, outcome: null, tag: 'SUCCEEDED', warningIcon: false },
        { status: 'failed', level: 'error', outcome: 'bounced', tag: 'FAILED', warningIcon: false },
    ] as const)(
        'shows only the $tag tag and a warning icon $warningIcon for a $status run with level $level and outcome $outcome',
        ({ status, level, outcome, tag, warningIcon }) => {
            const { container } = render(<RunStatusCell row={runRow(status, level, outcome)} />)

            expect(Array.from(container.querySelectorAll('.LemonTag'), (el) => el.textContent)).toEqual([tag])
            expect(container.querySelector('svg') !== null).toBe(warningIcon)
        }
    )
})
