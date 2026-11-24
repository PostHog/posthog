import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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
        { status: 'succeeded', level: 'error', outcome: 'complained', tag: 'MARKED AS SPAM', warning: null },
        { status: 'succeeded', level: null, outcome: 'complained', tag: 'MARKED AS SPAM', warning: null },
        { status: 'succeeded', level: 'error', outcome: 'bounced', tag: 'EMAIL BOUNCED', warning: null },
        { status: 'succeeded', level: null, outcome: 'bounced', tag: 'EMAIL BOUNCED', warning: null },
        { status: 'succeeded', level: 'warn', outcome: null, tag: 'SUCCEEDED', warning: 'Logged a warning' },
        { status: 'succeeded', level: 'error', outcome: null, tag: 'SUCCEEDED', warning: 'Logged an error' },
        { status: 'succeeded', level: null, outcome: null, tag: 'SUCCEEDED', warning: null },
        { status: 'failed', level: 'error', outcome: 'bounced', tag: 'FAILED', warning: null },
    ] as const)(
        'shows only $tag and warning $warning for a $status run with level $level and outcome $outcome',
        ({ status, level, outcome, tag, warning }) => {
            const { container, queryByLabelText } = render(<RunStatusCell row={runRow(status, level, outcome)} />)

            expect(container.textContent).toBe(tag)
            expect(queryByLabelText(/^Logged an? (error|warning)$/)?.getAttribute('aria-label') ?? null).toBe(warning)
        }
    )

    it.each([
        { level: 'error', note: /The run also logged an error\./ },
        { level: 'warn', note: /The run also logged a warning\./ },
    ] as const)('names a separate $level in the email outcome tooltip', async ({ level, note }) => {
        render(<RunStatusCell row={runRow('succeeded', level, 'bounced')} />)

        userEvent.hover(screen.getByText('EMAIL BOUNCED'))

        expect(await screen.findByText(note, {}, { timeout: 3000 })).toBeInTheDocument()
    })
})
