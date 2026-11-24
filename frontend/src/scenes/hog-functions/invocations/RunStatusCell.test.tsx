import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
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
            const { container, queryAllByLabelText } = render(<RunStatusCell row={runRow(status, level, outcome)} />)

            expect(container.textContent).toBe(tag)
            expect(
                queryAllByLabelText(/^Logged an? (error|warning)$/).map((icon) => icon.getAttribute('aria-label'))
            ).toEqual(warning ? [warning] : [])
        }
    )

    it.each([
        { level: 'error', alsoLogged: 'The run also logged an error.' },
        { level: 'warn', alsoLogged: 'The run also logged a warning.' },
        { level: null, alsoLogged: null },
    ] as const)('email outcome tooltip names a separate $level as $alsoLogged', async ({ level, alsoLogged }) => {
        jest.useFakeTimers()
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
        render(<RunStatusCell row={runRow('succeeded', level, 'bounced')} />)

        await user.hover(screen.getByText('EMAIL BOUNCED'))
        act(() => {
            jest.advanceTimersByTime(1000)
        })

        expect(
            screen.getByText(/refused the email/).textContent?.match(/The run also logged an? \w+\./)?.[0] ?? null
        ).toBe(alsoLogged)
        jest.useRealTimers()
    })
})
