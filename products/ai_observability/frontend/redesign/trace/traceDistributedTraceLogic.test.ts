import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { traceDistributedTraceLogic } from './traceDistributedTraceLogic'

const OTEL_ID = '4bf92f3577b34da6a3ce929d0e0e4736'
const GATEWAY_ID = '4bf92f35-77b3-4da6-a3ce-929d0e0e4736'

describe('traceDistributedTraceLogic', () => {
    let requestedIds: string[]
    let response: [number, object]

    async function mountedLogic(): Promise<ReturnType<typeof traceDistributedTraceLogic.build>> {
        const logic = traceDistributedTraceLogic({ traceId: GATEWAY_ID, timestampHint: null })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    beforeEach(() => {
        requestedIds = []
        useMocks({
            get: {
                '/api/projects/:team_id/tracing/spans/stored_trace/': ({ request }) => {
                    requestedIds.push(String(new URL(request.url).searchParams.get('trace_id')))
                    return response
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['the id the server names', [200, { traceId: OTEL_ID }], OTEL_ID],
        ['no id when Tracing holds no spans', [200, { traceId: null }], null],
        ['no id when the read fails', [500, { detail: 'nope' }], null],
    ])('holds %s', async (_description, serverResponse, expected) => {
        const toast = jest.spyOn(lemonToast, 'error')
        response = serverResponse as [number, object]

        const logic = await mountedLogic()

        expect(requestedIds).toEqual([GATEWAY_ID])
        expect(logic.values.distributedTraceId).toEqual(expected)
        expect(toast).not.toHaveBeenCalled()
    })
})
