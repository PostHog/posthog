import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SessionListApi, SessionPageRequestApi } from '../../generated/api.schemas'
import { ready } from '../traces/testFixtures'
import { SessionCellRead, sessionCellsLogic } from './sessionCellsLogic'
import { sessionsListLogic } from './sessionsListLogic'
import {
    SESSION_CELL_URLS,
    makeSessionCellsAnswer,
    makeSessionListItem,
    makeSessionPersonItem,
    makeSessionPreview,
} from './testFixtures'

const SESSIONS_URL = '/api/projects/:team_id/ai_observability/sessions/'
const SESSION_URL = '/api/projects/:team_id/ai_observability/sessions/:id/'
const FIRST_PAGE: SessionListApi = {
    items: [makeSessionListItem({ id: 'session-a' }), makeSessionListItem({ id: 'session-b' })],
    nextCursor: 'cursor-2',
}
const SECOND_PAGE: SessionListApi = {
    items: [makeSessionListItem({ id: 'session-c' })],
    nextCursor: null,
}
const FAILED: [number, unknown] = [500, { detail: 'boom' }]

describe('sessionCellsLogic', () => {
    let bodies: Record<SessionCellRead, SessionPageRequestApi[]>
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
                [SESSION_URL]: () => [200, makeSessionListItem({ id: 'session-z' })],
            },
            post: {
                [SESSION_CELL_URLS.titles]: async ({ request }: { request: Request }) => {
                    const body: SessionPageRequestApi = await request.json()
                    bodies.titles.push(body)
                    return titlesFail ? FAILED : [200, makeSessionCellsAnswer('titles', body.session_ids)]
                },
                [SESSION_CELL_URLS.people]: async ({ request }: { request: Request }) => {
                    const body: SessionPageRequestApi = await request.json()
                    bodies.people.push(body)
                    return [200, makeSessionCellsAnswer('people', body.session_ids)]
                },
            },
        })
        initKeaTests()
    })

    function mountAt(url: string): void {
        router.actions.push(url)
        logic = sessionCellsLogic()
        logic.mount()
    }

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('reads titles and people by session id', async () => {
        mountAt(urls.aiObservabilitySessions())
        await settle()

        expect(bodies.titles).toEqual([{ session_ids: ['session-a', 'session-b'] }])
        expect(bodies.people).toEqual([{ session_ids: ['session-a', 'session-b'] }])
        expect(logic.values.titles.get('session-b')).toEqual(ready(makeSessionPreview('session-b')))
        expect(logic.values.people.get('session-b')).toEqual(ready(makeSessionPersonItem('session-b').person))
    })

    it('marks the sessions of a failed title read as failed and still fills their people', async () => {
        titlesFail = true
        jest.spyOn(posthog, 'captureException')

        mountAt(urls.aiObservabilitySessions())
        await settle()

        expect(statuses(logic.values.titles, ['session-a', 'session-b'])).toEqual(['error', 'error'])
        expect(statuses(logic.values.people, ['session-a', 'session-b'])).toEqual(['ready', 'ready'])
    })

    it('reads the cells of the shown page again on reload', async () => {
        mountAt(urls.aiObservabilitySessions())
        await settle()

        sessionsListLogic.actions.reload()
        await settle()

        expect(bodies.titles.map((body) => body.session_ids)).toEqual([
            ['session-a', 'session-b'],
            ['session-a', 'session-b'],
        ])
        expect(bodies.people).toHaveLength(2)
    })

    it('reads only the sessions of a page it has not read', async () => {
        mountAt(urls.aiObservabilitySessions())
        await settle()

        sessionsListLogic.actions.showNextPage()
        await settle()
        sessionsListLogic.actions.showPreviousPage()
        sessionsListLogic.actions.showNextPage()
        await settle()

        expect(bodies.titles.map((body) => body.session_ids)).toEqual([['session-a', 'session-b'], ['session-c']])
    })

    it('reads the cells of a linked session the list does not show', async () => {
        mountAt(`${urls.aiObservabilitySessions()}?session=session-z`)
        await settle()

        expect(bodies.titles.map((body) => body.session_ids)).toEqual([['session-a', 'session-b'], ['session-z']])
        expect(logic.values.titles.get('session-z')).toEqual(ready(makeSessionPreview('session-z')))
        expect(logic.values.people.get('session-z')).toEqual(ready(makeSessionPersonItem('session-z').person))
    })
})
