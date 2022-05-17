import { PluginEvent } from '@posthog/plugin-scaffold'
import { mocked } from 'ts-jest/utils'

import { PreIngestionEvent } from '../../../../src/types'
import { determineShouldBufferStep } from '../../../../src/worker/ingestion/event-pipeline/determineShouldBufferStep'
import { shouldSendEventToBuffer } from '../../../../src/worker/ingestion/ingest-event'

jest.mock('../../../../src/worker/ingestion/ingest-event')

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    siteUrl: 'example.com',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00Z',
    event: '$pageview',
    properties: {},
    elementsList: [],
}

describe('determineShouldBufferStep()', () => {
    let runner: any
    const testPerson: any = { id: 'testid' }

    beforeEach(() => {
        runner = {
            nextStep: (...args: any[]) => args,
            hub: {
                db: { fetchPerson: () => Promise.resolve(testPerson) },
                eventsProcessor: {
                    produceEventToBuffer: jest.fn(),
                },
            },
        }
    })

    it('calls `produceEventToBuffer` if event should be buffered, stops processing', async () => {
        mocked(shouldSendEventToBuffer).mockReturnValue(true)

        const response = await determineShouldBufferStep(runner, preIngestionEvent)

        expect(runner.hub.eventsProcessor.produceEventToBuffer).toHaveBeenCalledWith(preIngestionEvent)
        expect(response).toEqual(null)
    })

    it('calls `createEventStep` next if not buffering', async () => {
        mocked(shouldSendEventToBuffer).mockReturnValue(false)

        const response = await determineShouldBufferStep(runner, preIngestionEvent)

        expect(response).toEqual(['createEventStep', preIngestionEvent, testPerson])
        expect(runner.hub.eventsProcessor.produceEventToBuffer).not.toHaveBeenCalled()
    })
})
