import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SessionListItemApi, SessionPageRequestApi } from '../../generated/api.schemas'
import { sessionPageLogic } from './sessionPageLogic'
import {
    SESSION_CELL_URLS,
    makeSessionCellsAnswer,
    makeSessionListItem,
    makeSessionPreview,
    sessionCellsMocks,
} from './testFixtures'

const SESSION_URL = '/api/projects/:team_id/ai_observability/sessions/:id/'
const UNSAFE_ID = 'a/b%c ü'
const UNSAFE_SEGMENT = 'YS9iJWMgw7w'
const LINK_TIMESTAMP = '2026-08-01T10:00:00Z'

type SessionAnswer = [number, SessionListItemApi | { detail: string }]

describe('sessionPageLogic', () => {
    let sessionReads: { id: string; params: Record<string, string> }[]
    let sessionAnswer: SessionAnswer
    let logic: ReturnType<typeof sessionPageLogic.build>

    async function mountAt(sessionId: string, params: Record<string, string> = {}): Promise<void> {
        router.actions.push(urls.aiObservabilitySession(sessionId, params))
        logic = sessionPageLogic({ sessionId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        sessionReads = []
        sessionAnswer = [200, makeSessionListItem({ id: UNSAFE_ID })]
        useMocks({
            get: {
                [SESSION_URL]: ({ request, params }) => {
                    sessionReads.push({
                        id: String(params.id),
                        params: Object.fromEntries(new URL(request.url).searchParams),
                    })
                    return sessionAnswer
                },
            },
            post: sessionCellsMocks(),
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('loads the session with the timestamp hint, and its title and person by session id', async () => {
        const cellBodies: SessionPageRequestApi[] = []
        useMocks({
            post: {
                [SESSION_CELL_URLS.titles]: async ({ request }: { request: Request }) => {
                    const body: SessionPageRequestApi = await request.json()
                    cellBodies.push(body)
                    return [200, makeSessionCellsAnswer('titles', body.session_ids)]
                },
            },
        })

        await mountAt(UNSAFE_ID, { timestamp: LINK_TIMESTAMP })

        expect(sessionReads).toEqual([{ id: UNSAFE_SEGMENT, params: { timestamp_hint: '2026-08-01T10:00:00.000Z' } }])
        expect(cellBodies).toEqual([{ session_ids: [UNSAFE_ID] }])
        expect(logic.values).toMatchObject({ status: 'ready', session: { id: UNSAFE_ID } })
        expect(logic.values.title).toEqual({ status: 'ready', value: makeSessionPreview(UNSAFE_ID) })
        expect(logic.values.person).toMatchObject({ status: 'ready', value: { label: 'Ana Example' } })
        expect(logic.values.sessionsHref).toEqual(urls.aiObservabilitySessions())
    })

    it.each([
        ['text that is no date', 'not-a-date'],
        ['a time no session can have started at', '9999-01-01T00:00:00Z'],
        ['the string a missing timestamp turns into', 'undefined'],
    ])('drops %s instead of sending it', async (_name, timestamp) => {
        await mountAt('session-1', { timestamp })

        expect(sessionReads).toEqual([{ id: 'c2Vzc2lvbi0x', params: {} }])
        expect(logic.values.status).toEqual('ready')
    })

    it('unknown session shows the not-found state', async () => {
        sessionAnswer = [404, { detail: 'Session not found.' }]

        await mountAt('session-1')

        expect(logic.values).toMatchObject({ status: 'not_found', session: null })
    })

    it('a retry reads again the session, its title and its person', async () => {
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        const failed: [number, { detail: string }] = [500, { detail: 'boom' }]
        sessionAnswer = failed
        useMocks({ post: { [SESSION_CELL_URLS.titles]: failed, [SESSION_CELL_URLS.people]: failed } })
        await mountAt('session-1')
        expect(logic.values).toMatchObject({
            status: 'failed',
            title: { status: 'error' },
            person: { status: 'error' },
        })

        sessionAnswer = [200, makeSessionListItem({ id: 'session-1' })]
        useMocks({ post: sessionCellsMocks() })
        logic.actions.reload()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            status: 'ready',
            session: { id: 'session-1' },
            title: { status: 'ready' },
            person: { status: 'ready' },
        })
    })
})
