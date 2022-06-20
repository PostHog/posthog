import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/2-prepareEventStep'
import { resetTestDatabase } from '../../../helpers/sql'

jest.mock('../../../../src/utils/status')

const pluginEvent: PluginEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 2,
    now: '2020-02-23T02:15:00Z',
    timestamp: '2020-02-23T02:15:00Z',
    event: 'default event',
    properties: {},
    uuid: '017ef865-19da-0000-3b60-1506093bf40f',
}

describe('prepareEventStep()', () => {
    let runner: any
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub()

        // :KLUDGE: We test below whether kafka messages are produced, so make sure the person exists beforehand.
        await hub.db.createPerson(
            DateTime.utc(),
            {},
            {},
            {},
            pluginEvent.team_id,
            null,
            false,
            new UUIDT().toString(),
            ['my_id']
        )
        hub.db.kafkaProducer!.queueMessage = jest.fn()

        runner = {
            nextStep: (...args: any[]) => args,
            hub,
        }
    })

    afterEach(async () => {
        await closeHub()
    })

    it('goes to `emitToBufferStep` for normal events', async () => {
        const response = await prepareEventStep(runner, pluginEvent)

        expect(response).toEqual([
            'emitToBufferStep',
            {
                distinctId: 'my_id',
                elementsList: [],
                event: 'default event',
                eventUuid: '017ef865-19da-0000-3b60-1506093bf40f',
                ip: '127.0.0.1',
                properties: {
                    $ip: '127.0.0.1',
                },
                teamId: 2,
                timestamp: expect.any(DateTime),
            },
        ])
        expect(hub.db.kafkaProducer!.queueMessage).not.toHaveBeenCalled()
    })

    it('produces to kafka and to `runAsyncHandlersStep` for $snapshot events', async () => {
        const response = await prepareEventStep(runner, { ...pluginEvent, event: '$snapshot' })

        expect(response).toEqual([
            'runAsyncHandlersStep',
            {
                distinctId: 'my_id',
                elementsList: [],
                event: '$snapshot',
                eventUuid: '017ef865-19da-0000-3b60-1506093bf40f',
                ip: '127.0.0.1',
                properties: {
                    $ip: '127.0.0.1',
                },
                teamId: 2,
                timestamp: '2020-02-23 02:15:00.000',
            },
        ])
        expect(hub.db.kafkaProducer!.queueMessage).toHaveBeenCalled()
    })

    it('does not continue if event is ignored', async () => {
        await hub.db.postgresQuery('UPDATE posthog_team SET session_recording_opt_in = $1', [false], 'testRecordings')

        const response = await prepareEventStep(runner, { ...pluginEvent, event: '$snapshot' })

        expect(response).toEqual(null)
        expect(hub.db.kafkaProducer!.queueMessage).not.toHaveBeenCalled()
    })

    it('re-normalizes event after plugins have been run', async () => {
        const response = await prepareEventStep(runner, {
            ...pluginEvent,
            properties: {
                $browser: 'Chrome',
            },
            $set: {
                someProp: 'value',
            },
        })

        expect(response).toEqual([
            'emitToBufferStep',
            {
                distinctId: 'my_id',
                elementsList: [],
                event: 'default event',
                eventUuid: '017ef865-19da-0000-3b60-1506093bf40f',
                ip: '127.0.0.1',
                properties: {
                    $ip: '127.0.0.1',
                    $browser: 'Chrome',
                    $set: {
                        someProp: 'value',
                    },
                    $set_once: {
                        $initial_browser: 'Chrome',
                    },
                },
                teamId: 2,
                timestamp: expect.any(DateTime),
            },
        ])
        expect(hub.db.kafkaProducer!.queueMessage).toHaveBeenCalled()
    })
})
