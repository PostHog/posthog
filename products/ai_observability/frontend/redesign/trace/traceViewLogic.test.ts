import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeTraceResource } from './adapter/testFixtures'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'

describe('traceViewLogic', () => {
    let requestedHint: string | null = null
    let requestedPath: string | null = null

    beforeEach(() => {
        requestedHint = null
        requestedPath = null
        useMocks({
            get: {
                [TRACE_URL]: ({ request }) => {
                    const url = new URL(request.url)
                    requestedHint = url.searchParams.get('timestamp_hint')
                    requestedPath = url.pathname
                    return [200, makeTraceResource({ name: null })]
                },
            },
        })
        initKeaTests()
    })

    afterEach(resumeKeaLoadersErrors)

    it('loads the trace by its encoded id with the link timestamp as the hint and derives the summary', async () => {
        const logic = traceViewLogic({ traceId: 'a/b', timestampHint: '2026-09-01T10:15:00Z' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready', traceName: 'Untitled trace' })
        expect(requestedPath).toMatch(/\/traces\/YS9i\/$/)
        expect(requestedHint).toEqual('2026-09-01T10:15:00Z')
        expect(logic.values.personLabel).toBe('ada@example.com')
        expect(logic.values.summary?.person).toEqual({
            label: 'ada@example.com',
            href: expect.stringContaining('user-1'),
        })
        expect(logic.values.tree[0].children.map((child) => child.id)).toEqual(['span-1', 'gen-1', 'gen-2'])
    })

    it.each([
        ['the trace is not found', 404, 'It may have been deleted, or it is outside the retention period.'],
        ['the request fails', 500, 'Something went wrong while loading it. Try again in a moment.'],
    ])('status is error when %s', async (_description, statusCode, expectedMessage) => {
        silenceKeaLoadersErrors()
        useMocks({ get: { [TRACE_URL]: () => [statusCode, { detail: 'nope' }] } })
        const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ status: 'error', errorMessage: expectedMessage })
    })
})
