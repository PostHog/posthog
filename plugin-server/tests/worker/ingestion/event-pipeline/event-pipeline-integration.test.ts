import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import fetch from 'node-fetch'

import { Hook, Hub } from '../../../../src/types'
import { closeHub, createHub } from '../../../../src/utils/db/hub'
import { PostgresUse } from '../../../../src/utils/db/postgres'
import { convertToPostIngestionEvent } from '../../../../src/utils/event'
import { UUIDT } from '../../../../src/utils/utils'
import { ActionManager } from '../../../../src/worker/ingestion/action-manager'
import { ActionMatcher } from '../../../../src/worker/ingestion/action-matcher'
import {
    processOnEventStep,
    processWebhooksStep,
} from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { HookCommander } from '../../../../src/worker/ingestion/hooks'
import { EventsProcessor } from '../../../../src/worker/ingestion/process-event'
import { setupPlugins } from '../../../../src/worker/plugins/setup'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../../helpers/clickhouse'
import { commonUserId } from '../../../helpers/plugins'
import { insertRow, resetTestDatabase } from '../../../helpers/sql'

jest.mock('../../../../src/utils/status')

describe('Event Pipeline integration test', () => {
    let hub: Hub
    let actionManager: ActionManager
    let actionMatcher: ActionMatcher
    let hookCannon: HookCommander

    const ingestEvent = async (event: PluginEvent) => {
        const runner = new EventPipelineRunner(hub, event, new EventsProcessor(hub))
        const result = await runner.runEventPipeline(event)
        const postIngestionEvent = convertToPostIngestionEvent(result.args[0])
        return Promise.all([
            processOnEventStep(runner.hub, postIngestionEvent),
            processWebhooksStep(postIngestionEvent, actionMatcher, hookCannon),
        ])
    }

    beforeEach(async () => {
        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
        process.env.SITE_URL = 'https://example.com'
        hub = await createHub()

        actionManager = new ActionManager(hub.db.postgres, hub)
        await actionManager.start()
        actionMatcher = new ActionMatcher(hub.db.postgres, actionManager, hub.teamManager)
        hookCannon = new HookCommander(
            hub.db.postgres,
            hub.teamManager,
            hub.organizationManager,
            hub.rustyHook,
            hub.appMetrics,
            hub.EXTERNAL_REQUEST_TIMEOUT_MS
        )

        jest.spyOn(hub.db, 'fetchPerson')
        jest.spyOn(hub.db, 'createPerson')
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('handles plugins setting properties', async () => {
        await resetTestDatabase(`
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
        `)
        await setupPlugins(hub)

        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            $set: { personProp: 1, anotherValue: 2 },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: 2,
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
                team_id: 2,
                timestamp: DateTime.fromISO(event.timestamp!, { zone: 'utc' }),
                // :KLUDGE: Ignore properties like $plugins_succeeded, etc
                properties: expect.objectContaining({
                    foo: 'bar',
                    $browser: 'Chrome',
                    processed: 'hell yes',
                    $set: {
                        personProp: 'value',
                        anotherValue: 2,
                        $browser: 'Chrome',
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
            $browser: 'Chrome',
            personProp: 'value',
            anotherValue: 2,
        })
    })

    it('fires a webhook', async () => {
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team SET slack_incoming_webhook = 'https://webhook.example.com/'`,
            [],
            'testTag'
        )

        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: 2,
            distinct_id: 'abc',
            ip: null,
            site_url: 'not-used-anymore',
            uuid: new UUIDT().toString(),
        }
        await actionManager.reloadAllActions()

        await ingestEvent(event)

        const expectedPayload = {
            text: '[Test Action](https://example.com/project/2/action/69) was triggered by [abc](https://example.com/project/2/person/abc)',
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

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_organization
                SET available_product_features = array ['{"key": "zapier", "name": "zapier"}'::jsonb]`,
            [],
            'testTag'
        )
        await insertRow(hub.db.postgres, 'ee_hook', {
            id: 'abc',
            team_id: 2,
            user_id: commonUserId,
            resource_id: 69,
            event: 'action_performed',
            target: 'https://example.com/',
            created: timestamp,
            updated: timestamp,
        } as Hook)

        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            timestamp: timestamp,
            now: timestamp,
            team_id: 2,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }
        await actionManager.reloadAllActions()

        await ingestEvent(event)

        const expectedPayload = {
            hook: {
                id: 'abc',
                event: 'action_performed',
                target: 'https://example.com/',
            },
            data: {
                event: 'xyz',
                properties: {
                    foo: 'bar',
                },
                eventUuid: expect.any(String),
                timestamp,
                teamId: 2,
                distinctId: 'abc',
                person: {
                    created_at: expect.any(String),
                    properties: {
                        $creator_event_uuid: event.uuid,
                    },
                    uuid: expect.any(String),
                },
                elementsList: [],
            },
        }

        // Using a more verbose way instead of toHaveBeenCalledWith because we need to parse request body
        // and use expect.any for a few payload properties, which wouldn't be possible in a simpler way
        expect(jest.mocked(fetch).mock.calls[0][0]).toBe('https://example.com/')
        const secondArg = jest.mocked(fetch).mock.calls[0][1]
        expect(JSON.parse(secondArg!.body as unknown as string)).toStrictEqual(expectedPayload)
        expect(JSON.parse(secondArg!.body as unknown as string)).toStrictEqual(expectedPayload)
        expect(secondArg!.headers).toStrictEqual({ 'Content-Type': 'application/json' })
        expect(secondArg!.method).toBe('POST')
    })

    it('single postgres action per run to create or load person', async () => {
        const event: PluginEvent = {
            event: 'xyz',
            properties: { foo: 'bar' },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: 2,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }

        await new EventPipelineRunner(hub, event, new EventsProcessor(hub)).runEventPipeline(event)

        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1) // we query before creating
        expect(hub.db.createPerson).toHaveBeenCalledTimes(1)

        // second time single fetch
        await new EventPipelineRunner(hub, event, new EventsProcessor(hub)).runEventPipeline(event)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(2)
    })
})
