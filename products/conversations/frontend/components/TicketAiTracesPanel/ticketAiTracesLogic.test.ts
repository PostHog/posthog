import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { LLMTrace } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ticketAiTracesLogic } from './ticketAiTracesLogic'

const PERSON_ID = '018f0000-0000-7000-8000-000000000001'
const TRACE: LLMTrace = { id: 'trace-1', createdAt: '2026-11-06T11:42:00Z', distinctId: 'customer-1', events: [] }

describe('ticketAiTracesLogic', () => {
    let logic: ReturnType<typeof ticketAiTracesLogic.build>
    let sentQuery: Record<string, unknown> | null

    beforeEach(() => {
        sentQuery = null
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    sentQuery = ((await request.json()) as { query: Record<string, unknown> }).query
                    return [200, { results: [TRACE], hasMore: true }]
                },
            },
        })
        initKeaTests()
        logic = ticketAiTracesLogic({ personId: PERSON_ID })
    })

    afterEach(() => {
        logic.unmount()
    })

    it("loads only the ticket person's traces, without staff impersonation traces", async () => {
        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadResultSuccess'])
            .toMatchValues({ result: { traces: [TRACE], hasMore: true } })

        expect(sentQuery).toMatchObject({
            kind: 'TracesQuery',
            personId: PERSON_ID,
            filterSupportTraces: true,
            dateRange: { date_from: '-30d' },
        })
    })
})
