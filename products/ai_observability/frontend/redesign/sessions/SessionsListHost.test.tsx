import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { SessionsListHost } from './SessionsListHost'
import {
    SESSION_TURNS_URL,
    makeSessionListItem,
    makeSessionListPage,
    makeSessionTurnPage,
    sessionCellsMocks,
    traceTurnsMocks,
} from './testFixtures'

const SESSIONS_URL = '/api/projects/:team_id/ai_observability/sessions/'
const SESSION_URL = '/api/projects/:team_id/ai_observability/sessions/:id/'
const TURNS_PAGE = makeSessionTurnPage([1, 2])

describe('SessionsListHost', () => {
    beforeEach(() => {
        useMocks({
            get: {
                [SESSIONS_URL]: [200, makeSessionListPage(['session-a', 'session-b'])],
                [SESSION_TURNS_URL]: [200, TURNS_PAGE],
            },
            post: { ...sessionCellsMocks(), ...traceTurnsMocks() },
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

    it('reload reads the open conversation again, so a turn the session gained shows', async () => {
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), { session: 'session-a' }).url)
        const view = render(<SessionsListHost />)
        await view.findByText('Answer of trace-2')
        useMocks({ get: { [SESSION_TURNS_URL]: [200, makeSessionTurnPage([1, 2, 3])] } })

        fireEvent.click(view.getByText('Reload'))

        expect(await view.findByText('Answer of trace-3')).toBeTruthy()
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

        await waitFor(() =>
            expect(router.values.searchParams).toEqual({ session: 'session-b', timestamp: '2026-09-01T10:15:00Z' })
        )
        await view.findByText('Answer of trace-2')
    })

    it('the open session steps to the next row and links its own page', async () => {
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), { session: 'session-a', date_from: '-24h' }).url)
        const view = render(<SessionsListHost />)
        await view.findByText('Answer of trace-2')
        const control = (name: string): HTMLElement => {
            const element = view.container.querySelector<HTMLElement>(`[data-attr="ai-observability-session-${name}"]`)
            if (!element) {
                throw new Error(`The header has no ${name} control`)
            }
            return element
        }

        const fullPage = combineUrl(control('full-page').getAttribute('href') ?? '')
        expect(fullPage.pathname).toMatch(/\/ai-observability\/sessions\/session-a$/)
        expect(fullPage.searchParams).toEqual({ timestamp: '2026-09-01T10:15:00Z', date_from: '-24h' })
        expect(control('previous').getAttribute('aria-disabled')).toEqual('true')

        fireEvent.click(control('next'))

        await waitFor(() =>
            expect(router.values.searchParams).toEqual({
                session: 'session-b',
                timestamp: '2026-09-01T10:15:00Z',
                date_from: '-24h',
            })
        )
    })

    it('a linked session off the loaded page reads its turns while its header is looked up', async () => {
        const turnReads: Record<string, string>[] = []
        let answerSession: (() => void) | undefined
        useMocks({
            get: {
                [SESSION_URL]: async () => {
                    await new Promise<void>((resolve) => (answerSession = resolve))
                    return [200, makeSessionListItem({ id: 'session-z', turnCount: 9 })]
                },
                [SESSION_TURNS_URL]: ({ request }) => {
                    turnReads.push(Object.fromEntries(new URL(request.url).searchParams))
                    return [200, TURNS_PAGE]
                },
            },
        })
        router.actions.push(
            combineUrl(urls.aiObservabilitySessions(), { session: 'session-z', timestamp: '2026-08-01T10:00:00Z' }).url
        )
        const view = render(<SessionsListHost />)

        await view.findByText('Answer of trace-2')
        expect(turnReads).toEqual([{ limit: '20', timestamp_hint: '2026-08-01T10:00:00.000Z' }])
        expect(view.queryByText(/9 turns/)).toBeNull()

        answerSession?.()
        await view.findByText(/9 turns/)
    })
})
