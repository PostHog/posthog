import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import fetch from 'node-fetch'
import { MockedFunction } from 'ts-jest/dist/utils/testing'

import { Hook, Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { ActionMatcher } from '../../../src/worker/ingestion/action-matcher'
import { ingestEvent } from '../../../src/worker/ingestion/ingest-event'
import { commonUserId } from '../../helpers/plugins'
import { insertRow, resetTestDatabase } from '../../helpers/sql'

describe('ingestEvent', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let actionMatcher: ActionMatcher
    let actionCounter: number

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeServer] = await createHub()
        actionMatcher = hub.actionMatcher
        actionCounter = 0
    })

    afterEach(async () => {
        await closeServer()
    })

    describe('conversion buffer', () => {
        beforeEach(() => {
            hub.CONVERSION_BUFFER_ENABLED = true
        })

        afterEach(() => {
            hub.CONVERSION_BUFFER_ENABLED = false
        })

        afterAll(() => {
            jest.clearAllMocks()
        })

        it('events from recently created persons are sent to the buffer', async () => {
            hub.eventsProcessor.produceEventToBuffer = jest.fn()

            // will create a new person
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

            await ingestEvent(hub, event)

            expect(hub.eventsProcessor.produceEventToBuffer).toHaveBeenCalled()
        })

        it('anonymous events are not sent to the buffer', async () => {
            hub.eventsProcessor.produceEventToBuffer = jest.fn()

            const event: PluginEvent = {
                event: 'xyz',
                properties: { foo: 'bar', $device_id: 'anonymous' },
                timestamp: new Date().toISOString(),
                now: new Date().toISOString(),
                team_id: 2,
                distinct_id: 'anonymous',
                ip: null,
                site_url: 'https://example.com',
                uuid: new UUIDT().toString(),
            }

            await ingestEvent(hub, event)

            expect(hub.eventsProcessor.produceEventToBuffer).not.toHaveBeenCalled()
        })
    })

    it('$identify events are not sent to the buffer', async () => {
        hub.eventsProcessor.produceEventToBuffer = jest.fn()

        const event: PluginEvent = {
            event: '$identify',
            properties: { foo: 'bar' },
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            team_id: 2,
            distinct_id: 'foo',
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }

        await ingestEvent(hub, event)

        expect(hub.eventsProcessor.produceEventToBuffer).not.toHaveBeenCalled()
    })
})
