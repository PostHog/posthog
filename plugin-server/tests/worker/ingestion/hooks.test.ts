import { DateTime } from 'luxon'
import { fetch } from 'undici'

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
            }
            hookCommander = new HookCommander(
                {} as any,
                {} as any,
                { enqueueIfEnabledForTeam: async () => Promise.resolve(false) } as any,
                { queueError: () => Promise.resolve(), queueMetric: () => Promise.resolve() } as unknown as AppMetrics,
                20000
            )
        })

        test('person = undefined', async () => {
            await hookCommander.postWebhook({ event: 'foo', properties: {} } as PostIngestionEvent, action, team, hook)

            expect(fetch).toHaveBeenCalledTimes(1)

            expect(jest.mocked(fetch).mock.calls[0][0]).toMatchInlineSnapshot(`"https://example.com/"`)
            expect(jest.mocked(fetch).mock.calls[0][1]?.body).toMatchInlineSnapshot(`
                "{
                    "hook": {
                        "id": "id",
                        "event": "foo",
                        "target": "https://example.com/"
                    },
                    "data": {
                        "event": "foo",
                        "properties": {},
                        "elementsList": [],
                        "person": {}
                    }
                }"
            `)
        })

        test('person data from the event', async () => {
            const now = DateTime.utc(2024, 1, 1).toISO()
            const uuid = '018f39d3-d94c-0000-eeef-df4a793f8844'
            await hookCommander.postWebhook(
                // @ts-expect-error TODO: Fix underlying type
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

            expect(jest.mocked(fetch).mock.calls[0][0]).toMatchInlineSnapshot(`"https://example.com/"`)
            expect(jest.mocked(fetch).mock.calls[0][1]?.body).toMatchInlineSnapshot(`
                "{
                    "hook": {
                        "id": "id",
                        "event": "foo",
                        "target": "https://example.com/"
                    },
                    "data": {
                        "eventUuid": "018f39d3-d94c-0000-eeef-df4a793f8844",
                        "event": "foo",
                        "teamId": 1,
                        "distinctId": "WALL-E",
                        "properties": {},
                        "timestamp": "2024-01-01T00:00:00.000Z",
                        "elementsList": [],
                        "person": {
                            "uuid": "018f39d3-d94c-0000-eeef-df4a793f8844",
                            "properties": {
                                "foo": "bar"
                            },
                            "created_at": "2024-01-01T00:00:00.000Z"
                        }
                    }
                }"
            `)
        })

        test('private IP hook forbidden in prod', async () => {
            process.env.NODE_ENV = 'production'

            const err = await hookCommander
                .postWebhook({ event: 'foo', properties: {} } as PostIngestionEvent, action, team, {
                    ...hook,
                    target: 'http://localhost:8000',
                })
                .catch((err) => err)

            expect(err.name).toBe('TypeError')
            expect(err.cause.name).toBe('SecureRequestError')
            expect(err.cause.message).toContain('Hostname is not allowed')
        })
    })
})
