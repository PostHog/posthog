import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SessionListItemApi, TracePreviewApi } from '../../generated/api.schemas'
import { TRACE_CELL_URLS, makeTracePreview } from '../traces/testFixtures'
import { sessionPageLogic } from './sessionPageLogic'
import { makeSessionListItem, sessionCellsMocks } from './testFixtures'

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

    function crumbNames(): unknown[] {
        return logic.values.breadcrumbs.map((crumb) => ('name' in crumb ? crumb.name : null))
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

    it('loads the session with the timestamp hint', async () => {
        await mountAt(UNSAFE_ID, { timestamp: LINK_TIMESTAMP })

        expect(sessionReads).toEqual([{ id: UNSAFE_SEGMENT, params: { timestamp: '2026-08-01T10:00:00.000Z' } }])
        expect(logic.values).toMatchObject({ status: 'ready', notFound: false, session: { id: UNSAFE_ID } })
        expect(logic.values.title).toEqual({ status: 'ready', value: makeTracePreview(`${UNSAFE_ID}-first-trace`) })
        expect(logic.values.person).toMatchObject({ status: 'ready', value: { label: 'Ana Example' } })
        expect(crumbNames()).toEqual(['AI observability', 'Sessions', 'Why was I charged twice this month?'])
        expect(logic.values.breadcrumbs[1]).toMatchObject({ path: urls.aiObservabilitySessions() })
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

    it('names a session with no readable first message untitled', async () => {
        const preview: TracePreviewApi = makeTracePreview('session-1-first-trace', { input: null })
        useMocks({ post: { [TRACE_CELL_URLS.previews]: [200, { items: [preview] }] } })

        await mountAt('session-1')

        expect(crumbNames()).toEqual(['AI observability', 'Sessions', 'Untitled session'])
    })

    it('unknown session shows the not-found state', async () => {
        sessionAnswer = [404, { detail: 'Session not found.' }]

        await mountAt('session-1')

        expect(logic.values).toMatchObject({ status: 'not_found', notFound: true, session: null })
        expect(crumbNames()).toEqual(['AI observability', 'Sessions', 'Session'])
    })

    it('a failed read can be retried', async () => {
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        sessionAnswer = [500, { detail: 'boom' }]
        await mountAt('session-1')
        expect(logic.values).toMatchObject({ status: 'failed', notFound: false })

        sessionAnswer = [200, makeSessionListItem({ id: 'session-1' })]
        logic.actions.loadSession()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ status: 'ready', session: { id: 'session-1' } })
    })
})
