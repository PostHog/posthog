import { DateTime } from 'luxon'
import fetch, { FetchError } from 'node-fetch'

import { Action, Team } from '../../../src/types'
import { UUIDT } from '../../../src/utils/utils'
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
            await hookCommander.postWebhook({ event: 'foo' } as any, action, team, hook)

            expect(fetch).toHaveBeenCalledWith('https://example.com/', {
                body: JSON.stringify(
                    {
                        hook: {
                            id: 'id',
                            event: 'foo',
                            target: 'https://example.com/',
                        },
                        data: {
                            event: 'foo',
                            person: {}, // person becomes empty object if undefined
                        },
                    },
                    undefined,
                    4
                ),
                headers: { 'Content-Type': 'application/json' },
                method: 'POST',
                timeout: 20000,
            })
        })

        test('person data from the event', async () => {
            const now = new Date().toISOString()
            const uuid = new UUIDT().toString()
            await hookCommander.postWebhook(
                {
                    event: 'foo',
                    teamId: hook.team_id,
                    person_id: uuid,
                    person_properties: { foo: 'bar' },
                    person_created_at: DateTime.fromISO(now).toUTC(),
                } as any,
                action,
                team,
                hook
            )
            expect(fetch).toHaveBeenCalledWith('https://example.com/', {
                body: JSON.stringify(
                    {
                        hook: {
                            id: 'id',
                            event: 'foo',
                            target: 'https://example.com/',
                        },
                        data: {
                            event: 'foo',
                            teamId: hook.team_id,
                            person: {
                                uuid: uuid,
                                properties: { foo: 'bar' },
                                created_at: now,
                            },
                        },
                    },
                    undefined,
                    4
                ),
                headers: { 'Content-Type': 'application/json' },
                method: 'POST',
                timeout: 20000,
            })
        })

        test('private IP hook forbidden in prod', async () => {
            process.env.NODE_ENV = 'production'

            await expect(
                hookCommander.postWebhook({ event: 'foo' } as any, action, team, {
                    ...hook,
                    target: 'http://127.0.0.1',
                })
            ).rejects.toThrow(new FetchError('Internal hostname', 'posthog-host-guard'))
        })
    })
})
