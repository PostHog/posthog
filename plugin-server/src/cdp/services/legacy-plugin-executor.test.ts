import { DateTime } from 'luxon'

import {
    createHogExecutionGlobals,
    createHogFunction,
    createInvocation,
    insertHogFunction as _insertHogFunction,
} from '~/tests/cdp/fixtures'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { DESTINATION_PLUGINS_BY_ID } from '../legacy-plugins'
import { HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { LegacyPluginExecutorService } from './legacy-plugin-executor.service'

jest.setTimeout(1000)

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe('LegacyPluginExecutorService', () => {
    let service: LegacyPluginExecutorService
    let hub: Hub
    let team: Team
    let globals: HogFunctionInvocationGlobalsWithInputs
    let fn: HogFunctionType
    let mockFetch: jest.Mock

    beforeEach(async () => {
        hub = await createHub()
        service = new LegacyPluginExecutorService(hub)
        team = await getFirstTeam(hub)

        fn = createHogFunction({
            name: 'Plugin test',
            template_id: 'plugin-intercom',
        })

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        mockFetch = jest.fn(() =>
            Promise.resolve({
                status: 200,
                json: () =>
                    Promise.resolve({
                        status: 200,
                    }),
            } as any)
        )

        jest.spyOn(service, 'fetch').mockImplementation(mockFetch)

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
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('setupPlugin', () => {
        it('should setup a plugin on first call', async () => {
            jest.spyOn(DESTINATION_PLUGINS_BY_ID['intercom'] as any, 'setupPlugin')

            await service.execute(createInvocation(fn, globals))

            const results = Promise.all([
                service.execute(createInvocation(fn, globals)),
                service.execute(createInvocation(fn, globals)),
                service.execute(createInvocation(fn, globals)),
            ])

            expect(await results).toMatchObject([{ finished: true }, { finished: true }, { finished: true }])

            expect(DESTINATION_PLUGINS_BY_ID['intercom'].setupPlugin).toHaveBeenCalledTimes(1)
            expect(jest.mocked(DESTINATION_PLUGINS_BY_ID['intercom'].setupPlugin!).mock.calls[0][0])
                .toMatchInlineSnapshot(`
                {
                  "config": {
                    "ignoredEmailDomains": "dev.posthog.com",
                    "intercomApiKey": "1234567890",
                    "triggeringEvents": "$identify,mycustomevent",
                    "useEuropeanDataStorage": "No",
                  },
                  "fetch": [Function],
                  "global": {},
                  "logger": {
                    "debug": [Function],
                    "error": [Function],
                    "log": [Function],
                    "warn": [Function],
                  },
                }
            `)
        })
    })

    describe('onEvent', () => {
        it('should call the plugin onEvent method', async () => {
            jest.spyOn(DESTINATION_PLUGINS_BY_ID['intercom'] as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
            })

            const res = await service.execute(invocation)

            expect(DESTINATION_PLUGINS_BY_ID['intercom'].onEvent).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(DESTINATION_PLUGINS_BY_ID['intercom'].onEvent!).mock.calls[0][0]))
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
                    "team_id": 1,
                    "uuid": "uuid",
                  },
                  "properties": {
                    "email": "test@posthog.com",
                  },
                  "team_id": 1,
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

            expect(res.finished).toBe(true)
            expect(res.logs).toMatchInlineSnapshot(`
                [
                  {
                    "level": "debug",
                    "message": "Executing plugin intercom",
                    "timestamp": "2025-01-01T01:00:00.000+01:00",
                  },
                  {
                    "level": "info",
                    "message": "Contact test@posthog.com in Intercom found",
                    "timestamp": "2025-01-01T01:00:00.000+01:00",
                  },
                  {
                    "level": "info",
                    "message": "Sent event mycustomevent for test@posthog.com to Intercom",
                    "timestamp": "2025-01-01T01:00:00.000+01:00",
                  },
                  {
                    "level": "debug",
                    "message": "Execution successful",
                    "timestamp": "2025-01-01T01:00:00.000+01:00",
                  },
                ]
            `)
        })

        it('should mock out fetch if it is a test function', async () => {
            jest.spyOn(DESTINATION_PLUGINS_BY_ID['intercom'] as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.hogFunction.name = 'My function [CDP-TEST-HIDDEN]'
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            const res = await service.execute(invocation)

            expect(mockFetch).toHaveBeenCalledTimes(0)

            expect(DESTINATION_PLUGINS_BY_ID['intercom'].onEvent).toHaveBeenCalledTimes(1)

            expect(forSnapshot(res.logs.map((l) => l.message))).toMatchInlineSnapshot(`
                [
                  "Executing plugin intercom",
                  "Fetch called but mocked due to test function",
                  "Unable to search contact test@posthog.com in Intercom. Status Code: undefined. Error message: ",
                  "Execution successful",
                ]
            `)
        })

        it('should handle and collect errors', async () => {
            jest.spyOn(DESTINATION_PLUGINS_BY_ID['intercom'] as any, 'onEvent')

            const invocation = createInvocation(fn, globals)
            invocation.globals.event.event = 'mycustomevent'
            invocation.globals.event.properties = {
                email: 'test@posthog.com',
            }

            mockFetch.mockRejectedValue(new Error('Test error'))

            const res = await service.execute(invocation)

            expect(DESTINATION_PLUGINS_BY_ID['intercom'].onEvent).toHaveBeenCalledTimes(1)

            expect(res.error).toBeInstanceOf(Error)
            expect(forSnapshot(res.logs.map((l) => l.message))).toMatchInlineSnapshot(`
                [
                  "Executing plugin intercom",
                  "Plugin errored: Service is down, retry later",
                ]
            `)

            expect(res.error).toEqual(new Error('Service is down, retry later'))
        })
    })

    describe('smoke tests', () => {
        const testCases = Object.entries(DESTINATION_PLUGINS_BY_ID).map(([pluginId, plugin]) => ({
            name: pluginId,
            plugin,
        }))

        it.each(testCases)('should run the plugin: %s', async ({ name, plugin }) => {
            globals.event.event = '$identify' // Many plugins filter for this
            const invocation = createInvocation(fn, globals)

            invocation.hogFunction.template_id = `plugin-${plugin.id}`

            const inputs: Record<string, any> = {}

            for (const input of plugin.metadata.config) {
                if (!input.key) {
                    continue
                }

                if (input.default) {
                    inputs[input.key] = input.default
                    continue
                }

                if (input.type === 'choice') {
                    inputs[input.key] = input.choices[0]
                } else if (input.type === 'string') {
                    inputs[input.key] = 'test'
                }
            }

            invocation.hogFunction.name = name
            const res = await service.execute(invocation)

            expect(res.logs).toMatchSnapshot()
        })
    })
})
