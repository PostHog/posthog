import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { SessionPageHost } from './SessionPageHost'
import {
    SESSION_TRACES_URL,
    SESSION_TURNS_URL,
    makeSessionListItem,
    makeSessionTurnsPage,
    sessionCellsMocks,
    sessionTurnsMock,
} from './testFixtures'

const SESSION_URL = '/api/projects/:team_id/ai_observability/sessions/:id/'

describe('SessionPageHost', () => {
    let pageRequests: Record<string, string>[]

    beforeEach(() => {
        pageRequests = []
        useMocks({
            get: {
                [SESSION_URL]: [200, makeSessionListItem({ id: 'session-1' })],
                [SESSION_TRACES_URL]: ({ request }) => {
                    pageRequests.push(Object.fromEntries(new URL(request.url).searchParams))
                    return [200, makeSessionTurnsPage([3, 4], { previousCursor: 'cursor-before' })]
                },
            },
            post: { ...sessionCellsMocks(), [SESSION_TURNS_URL]: sessionTurnsMock() },
        })
        initKeaTests()
        localStorage.clear()
    })

    afterEach(cleanup)

    it('trace param opens around that turn with the drawer', async () => {
        router.actions.push(combineUrl(urls.aiObservabilitySession('session-1'), { trace: 'trace-4' }).url)
        const view = render(<SessionPageHost sessionId="session-1" />)

        await view.findByText('Answer of trace-4')
        expect(pageRequests[0]).toMatchObject({ session_id: 'session-1', around: 'trace-4' })
        expect(view.getByText('Why was I charged twice this month?')).toBeTruthy()
        const drawer = traceDrawerLogic({ listId: 'session-turns' })
        expect(drawer.values.openTraceId).toEqual('trace-4')
        expect(drawer.values.position).toEqual({ index: 1, total: 2 })
    })

    it('unknown session shows the not-found state with a way back to the sessions list', async () => {
        useMocks({ get: { [SESSION_URL]: [404, { detail: 'Session not found.' }] } })
        router.actions.push(combineUrl(urls.aiObservabilitySession('session-1'), { date_from: '-30d' }).url)
        const view = render(<SessionPageHost sessionId="session-1" />)

        await view.findByText('Session not found')
        fireEvent.click(view.getByText('Go to sessions'))

        await waitFor(() =>
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.aiObservabilitySessions())
        )
        expect(router.values.searchParams).toEqual({ date_from: '-30d' })
        expect(pageRequests).toEqual([])
    })
})
