import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    createExampleInvocation,
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction,
} from '../_tests/fixtures'
import { CyclotronJobInvocationHogFunction, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { CdpCyclotronShadowWorker } from './cdp-cyclotron-shadow-worker.consumer'

jest.setTimeout(1000)

describe('CdpCyclotronShadowWorker', () => {
    let processor: CdpCyclotronShadowWorker
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let globals: HogFunctionInvocationGlobalsWithInputs
    let invocation: CyclotronJobInvocationHogFunction

    beforeEach(async () => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        hub.CYCLOTRON_SHADOW_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_shadow'

        processor = new CdpCyclotronShadowWorker(hub, hub)

        fn = await insertHogFunction(
            hub.postgres,
            team.id,
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                template_id: 'template-webhook',
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

        mockFetch.mockClear()
        mockFetch.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(JSON.stringify({})),
            headers: {},
        } as any)
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    it('should process invocations with no-op fetch (mockFetch not called)', async () => {
        const results = await processor.processInvocations([invocation])
        const result = results[0]

        expect(result.finished).toBe(true)
        expect(result.error).toBe(undefined)
        expect(mockFetch).not.toHaveBeenCalled()
    })

    it('should still execute bytecode and produce logs', async () => {
        const results = await processor.processInvocations([invocation])
        const result = results[0]

        expect(result.finished).toBe(true)
        expect(result.logs.map((x) => x.message)).toEqual([
            'Fetch response:, {"status":200,"body":""}',
            expect.stringContaining('Function completed in'),
        ])
    })

    it('should skip Kafka monitoring in processBatch', async () => {
        const monitoringSpy = jest.spyOn(processor['hogFunctionMonitoringService'], 'queueInvocationResults')
        const flushSpy = jest.spyOn(processor['hogFunctionMonitoringService'], 'flush')
        processor['queueInvocationResults'] = jest.fn().mockResolvedValue(undefined)

        await processor.processBatch([invocation])

        expect(monitoringSpy).not.toHaveBeenCalled()
        expect(flushSpy).not.toHaveBeenCalled()
    })

    it('should skip watcher in processBatch', async () => {
        const watcherSpy = jest.spyOn(processor['hogWatcher'], 'observeResults')
        processor['queueInvocationResults'] = jest.fn().mockResolvedValue(undefined)

        await processor.processBatch([invocation])

        expect(watcherSpy).not.toHaveBeenCalled()
    })
})
