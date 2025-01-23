import { DateTime } from 'luxon'

import {
    createHogExecutionGlobals,
    createInvocation,
    insertHogFunction as _insertHogFunction,
} from '~/tests/cdp/fixtures'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { PLUGINS_BY_ID } from '../legacy-plugins'
import { HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { CdpCyclotronWorkerPlugins } from './cdp-cyclotron-plugins-worker.consumer'

jest.mock('../../../src/utils/fetch', () => {
    return {
        trackedFetch: jest.fn(() =>
            Promise.resolve({
                status: 200,
                text: () => Promise.resolve(JSON.stringify({ success: true })),
                json: () => Promise.resolve({ success: true }),
            })
        ),
    }
})

const mockFetch: jest.Mock = require('../../../src/utils/fetch').trackedFetch

jest.setTimeout(1000)

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe('CdpCyclotronWorkerPlugins', () => {
    let processor: CdpCyclotronWorkerPlugins
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let globals: HogFunctionInvocationGlobalsWithInputs

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, {
            ...hogFunction,
            type: 'destination',
        })
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()

        team = await getFirstTeam(hub)

        processor = new CdpCyclotronWorkerPlugins(hub)

        await processor.start()

        mockFetch.mockClear()

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        fn = await insertHogFunction({
            name: 'Plugin test',
            template_id: 'plugin-intercom',
        })
        globals = {
            ...createHogExecutionGlobals({
                project: {
                    id: team.id,
                } as any,
                event: {
                    uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                        $lib_version: '1.0.0',
                        $set: {
                            email: 'test@posthog.com',
                        },
                    },
                    timestamp: fixedTime.toISO(),
                } as any,
            }),
            inputs: {
                intercomApiKey: '1234567890',
                triggeringEvents: '$identify,mycustomevent',
                ignoredEmailDomains: 'dev.posthog.com',
                useEuropeanDataStorage: 'No',
            },
        }
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('setupPlugin', () => {
        it('should setup a plugin on first call', async () => {
            jest.spyOn(PLUGINS_BY_ID['intercom'] as any, 'setupPlugin')

            const results = []

            results.push(processor.executePluginInvocation(createInvocation(fn, globals)))
            results.push(processor.executePluginInvocation(createInvocation(fn, globals)))
            results.push(processor.executePluginInvocation(createInvocation(fn, globals)))

            expect(await Promise.all(results)).toMatchObject([
                { finished: true },
                { finished: true },
                { finished: true },
            ])

            expect(PLUGINS_BY_ID['intercom'].setupPlugin).toHaveBeenCalledTimes(1)
            expect(jest.mocked(PLUGINS_BY_ID['intercom'].setupPlugin!).mock.calls[0][0]).toMatchInlineSnapshot(`
                {
                  "attachments": {},
                  "cache": {},
                  "config": {
                    "ignoredEmailDomains": "dev.posthog.com",
                    "intercomApiKey": "1234567890",
                    "triggeringEvents": "$identify,mycustomevent",
                    "useEuropeanDataStorage": "No",
                  },
                  "fetch": [Function],
                  "geoip": {},
                  "global": {},
                  "jobs": {},
                  "metrics": {},
                  "storage": {},
                  "utils": {},
                }
            `)
        })
    })

    describe('onEvent', () => {
        it('should call the plugin onEvent method', async () => {
            jest.spyOn(PLUGINS_BY_ID['intercom'] as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
            })

            await processor.executePluginInvocation(invocation)

            expect(PLUGINS_BY_ID['intercom'].onEvent).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(PLUGINS_BY_ID['intercom'].onEvent!).mock.calls[0][0]))
                .toMatchInlineSnapshot(`
                {
                  "distinct_id": "distinct_id",
                  "event": "mycustomevent",
                  "person": {
                    "created_at": "",
                    "properties": {
                      "email": "test@posthog.com",
                      "first_name": "Pumpkin",
                    },
                    "team_id": 2,
                    "uuid": "uuid",
                  },
                  "properties": {
                    "email": "test@posthog.com",
                  },
                  "team_id": 2,
                  "timestamp": "2025-01-01T00:00:00.000Z",
                  "uuid": "<REPLACED-UUID-0>",
                }
            `)

            expect(mockFetch).toHaveBeenCalledTimes(2)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://api.intercom.io/contacts/search",
                  {
                    "body": "{"query":{"field":"email","operator":"=","value":"test@posthog.com"}}",
                    "headers": {
                      "Accept": "application/json",
                      "Authorization": "Bearer 1234567890",
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)
            expect(forSnapshot(mockFetch.mock.calls[1])).toMatchInlineSnapshot(`
                [
                  "https://api.intercom.io/events",
                  {
                    "body": "{"event_name":"mycustomevent","created_at":null,"email":"test@posthog.com","id":"distinct_id"}",
                    "headers": {
                      "Accept": "application/json",
                      "Authorization": "Bearer 1234567890",
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)
        })

        it('should handle and collect errors', async () => {
            jest.spyOn(PLUGINS_BY_ID['intercom'] as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockRejectedValue(new Error('Test error'))

            const res = await processor.executePluginInvocation(invocation)

            expect(PLUGINS_BY_ID['intercom'].onEvent).toHaveBeenCalledTimes(1)

            expect(res.error).toBeInstanceOf(Error)
            expect(forSnapshot(res.logs)).toMatchInlineSnapshot(`
                [
                  {
                    "level": "debug",
                    "message": "Executing plugin intercom",
                    "timestamp": "2025-01-01T01:00:00.000+01:00",
                  },
                  {
                    "level": "error",
                    "message": "Plugin intercom execution failed",
                    "timestamp": "2025-01-01T01:00:00.000+01:00",
                  },
                ]
            `)
        })
    })
})
