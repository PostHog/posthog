import { DateTime } from 'luxon'

import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { UUIDT } from '~/utils/utils'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { HOG_EXAMPLES } from '../_tests/examples'
import {
    createExampleInvocation,
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction as _insertHogFunction,
} from '../_tests/fixtures'
import { CyclotronJobInvocationHogFunction, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

jest.setTimeout(1000)

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe('CdpCyclotronWorker', () => {
    let processor: CdpCyclotronWorker
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let globals: HogFunctionInvocationGlobalsWithInputs
    let invocation: CyclotronJobInvocationHogFunction

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new CdpCyclotronWorker(hub)

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        fn = await _insertHogFunction(
            hub.postgres,
            team.id,
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })
        )

        globals = {
            ...createHogExecutionGlobals({}),
            inputs: {
                url: 'https://posthog.com',
            },
        }

        invocation = createExampleInvocation(fn, globals)
        invocation.queueSource = 'postgres'
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('processInvocation', () => {
        beforeEach(() => {
            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
            } as any)
        })

        it('should process a single fetch invocation fully', async () => {
            const results = await processor.processInvocations([invocation])
            const result = results[0]

            expect(result.finished).toBe(true)
            expect(result.error).toBe(undefined)
            expect(result.metrics).toEqual([
                {
                    app_source_id: fn.id,
                    count: 1,
                    metric_kind: 'other',
                    metric_name: 'fetch',
                    team_id: team.id,
                },
            ])
            expect(result.logs.map((x) => x.message)).toEqual([
                'Executing function',
                "Suspending function due to async function call 'fetch'. Payload: 1239 bytes. Event: uuid",
                'Resuming function',
                'Fetch response:, {"status":200,"body":{}}',
                expect.stringContaining('Function completed in'),
            ])
        })

        it('should partially process an invocation if multiple fetches are required', async () => {
            mockFetch.mockResolvedValueOnce({
                status: 500,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
            } as any)

            const invocationId = invocation.id
            const results = await processor.processInvocations([invocation])
            const result = results[0]

            expect(result.finished).toBe(false)
            expect(result.error).toBe(undefined)
            expect(result.metrics).toEqual([])
            expect(result.invocation.id).toEqual(invocationId)
            expect(result.invocation.queue).toEqual('fetch')
            expect(result.invocation.queueScheduledAt).toBeDefined()
            expect(result.invocation.queueSource).toEqual('postgres')
            expect(result.invocation.queueParameters).toMatchInlineSnapshot(`
                {
                  "body": null,
                  "headers": {
                    "Content-Type": "application/json",
                  },
                  "method": "POST",
                  "return_queue": "hog",
                  "url": "https://posthog.com",
                }
            `)
            expect(result.invocation.queueMetadata).toMatchInlineSnapshot(`
                {
                  "trace": [
                    {
                      "headers": {},
                      "kind": "failurestatus",
                      "message": "Received failure status: 500",
                      "status": 500,
                      "timestamp": "2025-01-01T00:00:00.000Z",
                    },
                  ],
                  "tries": 1,
                }
            `)
            expect(result.logs.map((x) => x.message)).toEqual([
                'Executing function',
                "Suspending function due to async function call 'fetch'. Payload: 1239 bytes. Event: uuid",
            ])

            // Now invoke the result again

            const results2 = await processor.processInvocations([result.invocation])
            const result2 = results2[0]

            expect(result2.invocation.id).toEqual(invocationId)
            expect(result2.invocation.queueSource).toEqual('postgres')
            expect(result2.finished).toBe(true)
            expect(result2.error).toBe(undefined)
            expect(result2.metrics).toEqual([
                {
                    app_source_id: fn.id,
                    count: 1,
                    metric_kind: 'other',
                    metric_name: 'fetch',
                    team_id: team.id,
                },
            ])
            expect(result2.logs.map((x) => x.message)).toEqual([
                'Resuming function',
                'Fetch response:, {"status":200,"body":{}}',
                expect.stringContaining('Function completed in'),
            ])
        })

        it('should dequeue an invocation if the hog function cannot be found', async () => {
            const dequeueInvocationsSpy = jest
                .spyOn(processor['cyclotronJobQueue'], 'dequeueInvocations')
                .mockResolvedValue(undefined)
            const invocation = createExampleInvocation(fn, globals)
            invocation.functionId = new UUIDT().toString()
            const results = await processor.processInvocations([invocation])
            expect(results).toEqual([])
            expect(dequeueInvocationsSpy).toHaveBeenCalledWith([invocation])
        })
    })
})
