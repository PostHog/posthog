import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import fetch from 'node-fetch'

import { Hook, Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { commonUserId } from '../../../helpers/plugins'
import { insertRow, resetTestDatabase } from '../../../helpers/sql'

jest.mock('../../../../src/utils/status')

describe('Event Pipeline integration test', () => {
    let hub: Hub
    let closeServer: () => Promise<void>

    const ingestEvent = (event: PluginEvent) => new EventPipelineRunner(hub, event).runEventPipeline(event)

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeServer] = await createHub()
    })

    afterEach(async () => {
        await closeServer()
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
            team_id: 2,
            distinct_id: 'abc',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }

        await ingestEvent(event)

        const expectedPayload = {
            text: '[Test Action](https://example.com/action/69) was triggered by [abc](https://example.com/person/abc)',
        }

        expect(fetch).toHaveBeenCalledWith('https://webhook.example.com/', {
            body: JSON.stringify(expectedPayload, undefined, 4),
            headers: { 'Content-Type': 'application/json' },
            method: 'POST',
        })
    })

    it('fires a REST hook', async () => {
        await hub.db.postgresQuery(`UPDATE posthog_organization SET available_features = '{"zapier"}'`, [], 'testTag')
        await insertRow(hub.db.postgres, 'ee_hook', {
            id: 'abc',
            team_id: 2,
            user_id: commonUserId,
            resource_id: 69,
            event: 'action_performed',
            target: 'https://rest-hooks.example.com/',
            created: new Date().toISOString(),
            updated: new Date().toISOString(),
        } as Hook)

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

        await ingestEvent(event)

        const expectedPayload = {
            hook: {
                id: 'abc',
                event: 'action_performed',
                target: 'https://rest-hooks.example.com/',
            },
            data: {
                event: 'xyz',
                properties: {
                    foo: 'bar',
                },
                eventUuid: expect.any(String),
                timestamp: expect.any(String),
                teamId: 2,
                distinctId: 'abc',
                ip: null,
                elementsList: [],
                person: {
                    id: expect.any(Number),
                    created_at: expect.any(String),
                    team_id: 2,
                    properties: {},
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
})
