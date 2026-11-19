import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SessionListApi } from '../../generated/api.schemas'
import {
    TRACE_CELL_URLS,
    makeTraceCellsAnswer,
    makeTracePersonItem,
    makeTracePreview,
    ready,
} from '../traces/testFixtures'
import { sessionCellsLogic } from './sessionCellsLogic'
import { sessionsListLogic } from './sessionsListLogic'
import { makeSessionListItem } from './testFixtures'

const SESSIONS_URL = '/api/projects/:team_id/ai_observability/sessions/'
const FIRST_PAGE: SessionListApi = {
    items: [
        makeSessionListItem({ id: 'session-a', firstTraceId: 'trace-a', firstTraceCreatedAt: '2026-09-01T10:15:00Z' }),
        makeSessionListItem({ id: 'session-b', firstTraceId: 'trace-b', firstTraceCreatedAt: '2026-08-30T08:00:00Z' }),
    ],
    nextCursor: 'cursor-2',
}
const SECOND_PAGE: SessionListApi = {
    items: [makeSessionListItem({ id: 'session-c', firstTraceId: 'trace-c' })],
    nextCursor: null,
}
const FAILED: [number, unknown] = [500, { detail: 'boom' }]

type CellRead = 'titles' | 'people'
type CellBody = { trace_ids: string[]; earliest_created_at?: string; latest_created_at?: string }

describe('sessionCellsLogic', () => {
    let bodies: Record<CellRead, CellBody[]>
    let titlesFail: boolean
    let logic: ReturnType<typeof sessionCellsLogic.build>

    const statuses = (loads: ReadonlyMap<string, { status: string }>, ids: string[]): string[] =>
        ids.map((id) => loads.get(id)?.status ?? 'none')

    async function settle(): Promise<void> {
        await expectLogic(sessionsListLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        bodies = { titles: [], people: [] }
        titlesFail = false
        useMocks({
            get: {
                [SESSIONS_URL]: ({ request }) => [
                    200,
                    new URL(request.url).searchParams.get('cursor') === 'cursor-2' ? SECOND_PAGE : FIRST_PAGE,
                ],
            },
            post: {
                [TRACE_CELL_URLS.previews]: async ({ request }: { request: Request }) => {
                    const body: CellBody = await request.json()
                    bodies.titles.push(body)
                    return titlesFail ? FAILED : [200, makeTraceCellsAnswer('previews', body.trace_ids)]
                },
                [TRACE_CELL_URLS.people]: async ({ request }: { request: Request }) => {
                    const body: CellBody = await request.json()
                    bodies.people.push(body)
                    return [200, makeTraceCellsAnswer('people', body.trace_ids)]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.aiObservabilitySessions())
        logic = sessionCellsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('reads titles by first trace id', async () => {
        await settle()

        expect(bodies.titles).toEqual([{ trace_ids: ['trace-a', 'trace-b'] }])
        expect(bodies.people).toEqual([
            {
                trace_ids: ['trace-a', 'trace-b'],
                earliest_created_at: '2026-08-30T08:00:00Z',
                latest_created_at: '2026-09-01T10:15:00Z',
            },
        ])
        expect(logic.values.titles.get('trace-b')).toEqual(ready(makeTracePreview('trace-b')))
        expect(logic.values.people.get('trace-b')).toEqual(ready(makeTracePersonItem('trace-b').person))
    })

    it('marks the sessions of a failed title read as failed and still fills their people', async () => {
        titlesFail = true
        jest.spyOn(posthog, 'captureException')

        await settle()

        expect(statuses(logic.values.titles, ['trace-a', 'trace-b'])).toEqual(['error', 'error'])
        expect(statuses(logic.values.people, ['trace-a', 'trace-b'])).toEqual(['ready', 'ready'])
    })

    it('reads only the sessions of a page it has not read', async () => {
        await settle()

        sessionsListLogic.actions.showNextPage()
        await settle()
        sessionsListLogic.actions.showPreviousPage()
        sessionsListLogic.actions.showNextPage()
        await settle()

        expect(bodies.titles.map((body) => body.trace_ids)).toEqual([['trace-a', 'trace-b'], ['trace-c']])
    })
})
