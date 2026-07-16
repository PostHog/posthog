import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { SuspendedTag } from './LineageNode'

afterEach(cleanup)

describe('SuspendedTag', () => {
    it('shows suspension details when they are available', async () => {
        render(
            <SuspendedTag
                suspended={{
                    clickhouse: {
                        at: '2026-07-16T12:00:00Z',
                        reason: 'Query exceeded its resource limit',
                        job_id: 'job-id',
                    },
                }}
            />
        )

        await userEvent.hover(screen.getByText('suspended'))

        await waitFor(() => {
            expect(document.body.textContent).toContain('Query exceeded its resource limit')
        })
    })

    it('shows a safe fallback when legacy suspension details are unavailable', async () => {
        render(
            <SuspendedTag
                suspended={{
                    clickhouse: {
                        at: null,
                        reason: null,
                        job_id: null,
                    },
                }}
            />
        )

        await userEvent.hover(screen.getByText('suspended'))

        await waitFor(() => {
            expect(screen.getByText('Suspended (details unavailable)')).toBeTruthy()
        })
    })
})
