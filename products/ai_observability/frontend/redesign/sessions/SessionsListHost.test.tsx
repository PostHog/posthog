import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { SessionsListHost } from './SessionsListHost'
import {
    SESSION_TRACES_URL,
    SESSION_TURNS_URL,
    makeSessionListPage,
    makeSessionTurnsPage,
    sessionCellsMocks,
    sessionTurnsMock,
} from './testFixtures'

const SESSIONS_URL = '/api/projects/:team_id/ai_observability/sessions/'
const AVAILABILITY_URL = '/api/projects/:team_id/ai_observability/sessions/availability/'
const TURNS_PAGE = makeSessionTurnsPage([1, 2])

describe('SessionsListHost', () => {
    beforeEach(() => {
        useMocks({
            get: {
                [SESSIONS_URL]: [200, makeSessionListPage(['session-a', 'session-b'])],
                [AVAILABILITY_URL]: [200, { hasSessions: true }],
                [SESSION_TRACES_URL]: [200, TURNS_PAGE],
            },
            post: { ...sessionCellsMocks(), [SESSION_TURNS_URL]: sessionTurnsMock() },
        })
        initKeaTests()
        localStorage.clear()
    })

    afterEach(cleanup)

    it('clicking a message opens the trace drawer on that step with session and trace in the URL', async () => {
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), { session: 'session-a' }).url)
        const view = render(<SessionsListHost />)

        await view.findByText('Answer of trace-2')
        // Each turn shows its question then its answer, and each message offers its step.
        const viewSteps = view.container.querySelectorAll('[data-attr="trace-view-thread-view-step"]')
        expect(viewSteps).toHaveLength(4)
        fireEvent.click(viewSteps[3])

        await waitFor(() =>
            expect(router.values.searchParams).toEqual({
                session: 'session-a',
                trace: 'trace-2',
                ts: TURNS_PAGE.items[1].createdAt,
                step: 'trace-2-gen',
            })
        )
        expect(router.values.location.pathname).toContain(urls.aiObservabilitySessions())
        const drawer = traceDrawerLogic({ listId: 'session-turns' })
        expect(drawer.values.rows.map((row) => row.traceId)).toEqual(['trace-1', 'trace-2'])
        expect(drawer.values.position).toEqual({ index: 1, total: 2 })
    })

    it('opens a session from a click on its row', async () => {
        router.actions.push(urls.aiObservabilitySessions())
        const view = render(<SessionsListHost />)
        const rows = await waitFor(() => {
            const found = view.container.querySelectorAll('[data-attr="ai-observability-session-row"]')
            expect(found).toHaveLength(2)
            return found
        })

        fireEvent.click(rows[1])

        await waitFor(() => expect(router.values.searchParams).toEqual({ session: 'session-b' }))
        await view.findByText('Answer of trace-2')
    })

    it('shows the setup card instead of the list when the project has no sessions', async () => {
        useMocks({ get: { [AVAILABILITY_URL]: [200, { hasSessions: false }] } })
        router.actions.push(urls.aiObservabilitySessions())
        const view = render(<SessionsListHost />)

        await view.findByText('View traces instead')
        expect(view.container.querySelector('[data-attr="ai-observability-sessions-list"]')).toBeNull()
    })
})
