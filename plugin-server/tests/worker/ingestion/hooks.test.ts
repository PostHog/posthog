import { DateTime } from 'luxon'
import fetch, { FetchError } from 'node-fetch'

import { Action, ISOTimestamp, PostIngestionEvent, Team } from '../../../src/types'
import { AppMetrics } from '../../../src/worker/ingestion/app-metrics'
import { HookCommander } from '../../../src/worker/ingestion/hooks'
import { Hook } from './../../../src/types'

describe('hooks', () => {
    const team = { id: 123, person_display_name_properties: null } as Team
    beforeEach(() => {
        process.env.NODE_ENV = 'test'
    })

    describe('postRestHook', () => {
        let hookCommander: HookCommander
        let hook: Hook
        const action = {
            id: 1,
            name: 'action1',
            // slack_message_format: '[user.name] did thing from browser [user.brauzer]',
        } as Action

        beforeEach(() => {
            hook = {
                id: 'id',
                team_id: 1,
                user_id: 1,
                resource_id: 1,
                event: 'foo',
                target: 'https://example.com/',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
                format_text: null,
            }
            hookCommander = new HookCommander(
                {} as any,
                {} as any,
                {} as any,
                { enqueueIfEnabledForTeam: async () => Promise.resolve(false) },
                { queueError: () => Promise.resolve(), queueMetric: () => Promise.resolve() } as unknown as AppMetrics,
                20000
            )
        })

        test('person = undefined', async () => {
            await hookCommander.postWebhook({ event: 'foo', properties: {} } as PostIngestionEvent, action, team, hook)

            expect(fetch).toHaveBeenCalledTimes(1)
            expect(fetch.mock.calls[0]).toMatchInlineSnapshot(`
                Array [
                  "https://example.com/",
                  Object {
                    "body": "{
                    \\"hook\\": {
                        \\"id\\": \\"id\\",
                        \\"event\\": \\"foo\\",
                        \\"target\\": \\"https://example.com/\\"
                    },
                    \\"data\\": {
                        \\"event\\": \\"foo\\",
                        \\"properties\\": {},
                        \\"elementsList\\": [],
                        \\"person\\": {}
                    }
                }",
                    "headers": Object {
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                    "timeout": 20000,
                  },
                ]
            `)
        })

        test('person data from the event', async () => {
            const now = DateTime.utc(2024, 1, 1).toISO()
            const uuid = '018f39d3-d94c-0000-eeef-df4a793f8844'
            await hookCommander.postWebhook(
                {
                    eventUuid: uuid,
                    distinctId: 'WALL-E',
                    timestamp: now as ISOTimestamp,
                    event: 'foo',
                    teamId: hook.team_id,
                    properties: {},
                    person_id: uuid,
                    person_properties: { foo: 'bar' },
                    person_created_at: now as ISOTimestamp,
                } as PostIngestionEvent,
                action,
                team,
                hook
            )
            expect(fetch).toHaveBeenCalledTimes(1)
            expect(fetch.mock.calls[0]).toMatchInlineSnapshot(`
                Array [
                  "https://example.com/",
                  Object {
                    "body": "{
                    \\"hook\\": {
                        \\"id\\": \\"id\\",
                        \\"event\\": \\"foo\\",
                        \\"target\\": \\"https://example.com/\\"
                    },
                    \\"data\\": {
                        \\"eventUuid\\": \\"018f39d3-d94c-0000-eeef-df4a793f8844\\",
                        \\"event\\": \\"foo\\",
                        \\"teamId\\": 1,
                        \\"distinctId\\": \\"WALL-E\\",
                        \\"properties\\": {},
                        \\"timestamp\\": \\"2024-01-01T00:00:00.000Z\\",
                        \\"elementsList\\": [],
                        \\"person\\": {
                            \\"uuid\\": \\"018f39d3-d94c-0000-eeef-df4a793f8844\\",
                            \\"properties\\": {
                                \\"foo\\": \\"bar\\"
                            },
                            \\"created_at\\": \\"2024-01-01T00:00:00.000Z\\"
                        }
                    }
                }",
                    "headers": Object {
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                    "timeout": 20000,
                  },
                ]
            `)
        })

        test('private IP hook forbidden in prod', async () => {
            process.env.NODE_ENV = 'production'

            await expect(
                hookCommander.postWebhook({ event: 'foo', properties: {} } as PostIngestionEvent, action, team, {
                    ...hook,
                    target: 'http://127.0.0.1',
                })
            ).rejects.toThrow(new FetchError('Internal hostname', 'posthog-host-guard'))
        })
    })
})
