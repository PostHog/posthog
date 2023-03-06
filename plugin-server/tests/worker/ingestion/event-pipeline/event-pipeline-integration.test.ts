import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import fetch from 'node-fetch'
import { v4 } from 'uuid'

import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { setupPlugins } from '../../../../src/worker/plugins/setup'
import { delayUntilEventIngested } from '../../../helpers/clickhouse'
import { insertRow, resetTestDatabase } from '../../../helpers/sql'

jest.mock('../../../../src/utils/status')

describe('Event Pipeline integration test', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let teamId: number
    let actionId: number
    let userId: number

    const ingestEvent = async (event: PluginEvent) => {
        const runner = new EventPipelineRunner(hub, event)
        const result = await runner.runEventPipeline(event)
        const resultEvent = result.args[0]
        return runner.runAsyncHandlersEventPipeline(resultEvent)
    }

    beforeEach(async () => {
        ;({ teamId, actionId, userId } = await resetTestDatabase())
        ;[hub, closeServer] = await createHub()

        jest.spyOn(hub.db, 'fetchPerson')
    })

    afterEach(async () => {
        await closeServer()
    })

    it('handles plugins setting properties', async () => {
        ;({ teamId } = await resetTestDatabase(`
            function processEvent (event) {
                event.properties = {
                    ...event.properties,
                    $browser: 'Chrome',
                    processed: 'hell yes'
                }
                event.$set = {
                    ...event.$set,
                    personProp: 'value'
                }
                return event
            }
        `))
        await setupPlugins(hub)

        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            $set: { personProp: 1, anotherValue: 2 },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: teamId,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }

        await ingestEvent(event)

        const events = await delayUntilEventIngested(() => hub.db.fetchEvents())
        const persons = await delayUntilEventIngested(() => hub.db.fetchPersons())

        expect(events.length).toEqual(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                uuid: event.uuid,
                event: 'xyz',
                team_id: teamId,
                timestamp: DateTime.fromISO(event.timestamp!, { zone: 'utc' }),
                // :KLUDGE: Ignore properties like $plugins_succeeded, etc
                properties: expect.objectContaining({
                    foo: 'bar',
                    $browser: 'Chrome',
                    processed: 'hell yes',
                    $set: {
                        personProp: 'value',
                        anotherValue: 2,
                    },
                    $set_once: {
                        $initial_browser: 'Chrome',
                    },
                }),
            })
        )

        expect(persons.length).toEqual(1)
        expect(persons[0].version).toEqual(0)
        expect(persons[0].properties).toEqual({
            $creator_event_uuid: event.uuid,
            $initial_browser: 'Chrome',
            personProp: 'value',
            anotherValue: 2,
        })
    })

    it('fires a webhook', async () => {
        await hub.db.postgresQuery(
            `UPDATE posthog_team SET slack_incoming_webhook = 'https://webhook.example.com/'`,
            [],
            'testTag'
        )

        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: teamId,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }
        await hub.actionManager.reloadAllActions()

        await ingestEvent(event)

        const expectedPayload = {
            text: `[Test Action](https://example.com/action/${actionId}) was triggered by [abc](https://example.com/person/abc)`,
        }

        expect(fetch).toHaveBeenCalledWith('https://webhook.example.com/', {
            body: JSON.stringify(expectedPayload, undefined, 4),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST',
            timeout: 10000,
        })
    })

    it('fires a REST hook', async () => {
        const timestamp = new Date().toISOString()

        await hub.db.postgresQuery(`UPDATE posthog_organization SET available_features = '{"zapier"}'`, [], 'testTag')
        const { id: hookId } = await insertRow('ee_hook', {
            id: v4(),
            team_id: teamId,
            user_id: userId,
            resource_id: actionId,
            event: 'action_performed',
            target: 'https://rest-hooks.example.com/',
            created: timestamp,
            updated: timestamp,
        })

        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            timestamp: timestamp,
            now: timestamp,
            team_id: teamId,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }
        await hub.actionManager.reloadAllActions()

        await ingestEvent(event)

        const expectedPayload = {
            hook: {
                id: hookId,
                event: 'action_performed',
                target: 'https://rest-hooks.example.com/',
            },
            data: {
                event: 'xyz',
                properties: {
                    foo: 'bar',
                },
                eventUuid: expect.any(String),
                timestamp,
                teamId: teamId,
                distinctId: 'abc',
                ip: null,
                elementsList: [],
                person: {
                    id: expect.any(Number),
                    created_at: expect.any(String),
                    team_id: teamId,
                    properties: {
                        $creator_event_uuid: event.uuid,
                    },
                    uuid: expect.any(String),
                },
            },
        }

        // Using a more verbose way instead of toHaveBeenCalledWith because we need to parse request body
        // and use expect.any for a few payload properties, which wouldn't be possible in a simpler way
        expect(jest.mocked(fetch).mock.calls[0][0]).toBe('https://rest-hooks.example.com/')
        const secondArg = jest.mocked(fetch).mock.calls[0][1]
        expect(JSON.parse(secondArg!.body as unknown as string)).toStrictEqual(expectedPayload)
        expect(JSON.parse(secondArg!.body as unknown as string)).toStrictEqual(expectedPayload)
        expect(secondArg!.headers).toStrictEqual({ 'Content-Type': 'application/json' })
        expect(secondArg!.method).toBe('POST')
    })

    it('loads person data once', async () => {
        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: teamId,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }

        await new EventPipelineRunner(hub, event).runEventPipeline(event)

        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
    })
})
