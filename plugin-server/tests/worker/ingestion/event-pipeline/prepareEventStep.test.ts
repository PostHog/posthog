import { DateTime } from 'luxon'

import { Hub } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/prepareEventStep'
import { resetTestDatabase } from '../../../helpers/sql'

jest.mock('../../../../src/utils/status')

const pluginEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    now: '2020-02-23T02:15:00Z',
    timestamp: '2020-02-23T02:15:00Z',
    event: 'default event',
    properties: {},
    uuid: '017ef865-19da-0000-3b60-1506093bf40f',
}

const person = {
    id: 123,
    properties: {},
    is_user_id: 0,
    is_identified: true,
    uuid: new UUIDT().toString(),
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: DateTime.now(),
    version: 0,
}

describe('prepareEventStep()', () => {
    let runner: any
    let hub: Hub
    let closeHub: () => Promise<void>
    let teamId: number

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    beforeEach(async () => {
        ;({ teamId } = await resetTestDatabase())

        // :KLUDGE: We test below whether kafka messages are produced, so make sure the person exists beforehand.
        await hub.db.createPerson(person.created_at, {}, {}, {}, teamId, null, false, person.uuid, ['my_id'])
        hub.db.kafkaProducer!.queueMessage = jest.fn()

        runner = {
            nextStep: (...args: any[]) => args,
            hub,
        }
    })

    afterAll(async () => {
        await closeHub()
    })

    it('goes to `createEventStep` for normal events', async () => {
        const response = await prepareEventStep(runner, { ...pluginEvent, team_id: teamId })

        expect(response).toEqual({
            distinctId: 'my_id',
            elementsList: [],
            event: 'default event',
            eventUuid: '017ef865-19da-0000-3b60-1506093bf40f',
            ip: '127.0.0.1',
            properties: {
                $ip: '127.0.0.1',
            },
            teamId: teamId,
            timestamp: '2020-02-23T02:15:00.000Z',
        })
        expect(hub.db.kafkaProducer!.queueMessage).not.toHaveBeenCalled()
    })
})
