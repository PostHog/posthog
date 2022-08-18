import { DateTime } from 'luxon'

import { ISOTimestamp, Person, PreIngestionEvent } from '../../../../src/types'
import { UUIDT } from '../../../../src/utils/utils'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/5-createEventStep'
import { LazyPersonContainer } from '../../../../src/worker/ingestion/lazy-person-container'

jest.mock('../../../../src/worker/plugins/run')

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: [],
}

const person: Person = {
    id: 123,
    team_id: 2,
    properties: {},
    is_user_id: 0,
    is_identified: true,
    uuid: new UUIDT().toString(),
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: DateTime.now(),
    version: 0,
}

describe('createEventStep()', () => {
    let runner: any

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                eventsProcessor: {
                    createEvent: jest.fn().mockReturnValue(preIngestionEvent),
                },
            },
        }
    })

    it('calls `createEvent` and forwards to `runAsyncHandlersStep`', async () => {
        const personContainer = new LazyPersonContainer(2, 'my_id', runner.hub, person)
        const response = await createEventStep(runner, preIngestionEvent, personContainer)

        expect(response).toEqual(['runAsyncHandlersStep', preIngestionEvent, person])
    })
})
