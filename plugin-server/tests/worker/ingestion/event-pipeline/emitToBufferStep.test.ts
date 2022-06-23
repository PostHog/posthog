import { DateTime } from 'luxon'

import { Person, PreIngestionEvent } from '../../../../src/types'
import {
    emitToBufferStep,
    shouldSendEventToBuffer,
} from '../../../../src/worker/ingestion/event-pipeline/3-emitToBufferStep'

const now = DateTime.fromISO('2020-01-01T12:00:05.200Z')

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00Z',
    event: '$pageview',
    properties: {},
    elementsList: [],
}

const existingPerson: Person = {
    id: 123,
    team_id: 2,
    properties: {},
    is_user_id: 0,
    is_identified: true,
    uuid: 'uuid',
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: now.minus({ days: 1 }),
    version: 0,
}

let runner: any

beforeEach(() => {
    runner = {
        nextStep: (...args: any[]) => args,
        hub: {
            CONVERSION_BUFFER_ENABLED: true,
            BUFFER_CONVERSION_SECONDS: 60,
            db: { fetchPerson: jest.fn().mockResolvedValue(existingPerson) },
            eventsProcessor: {
                produceEventToBuffer: jest.fn(),
            },
        },
    }
})

describe('emitToBufferStep()', () => {
    it('calls `produceEventToBuffer` if event should be buffered, stops processing', async () => {
        const response = await emitToBufferStep(runner, preIngestionEvent, () => true)

        expect(runner.hub.eventsProcessor.produceEventToBuffer).toHaveBeenCalledWith(preIngestionEvent)
        expect(runner.hub.db.fetchPerson).toHaveBeenCalledWith(2, 'my_id')
        expect(response).toEqual(null)
    })

    it('calls `createEventStep` next if not buffering', async () => {
        const response = await emitToBufferStep(runner, preIngestionEvent, () => false)

        expect(response).toEqual(['createEventStep', { ...preIngestionEvent, person: existingPerson }])
        expect(runner.hub.db.fetchPerson).toHaveBeenCalledWith(2, 'my_id')
        expect(runner.hub.eventsProcessor.produceEventToBuffer).not.toHaveBeenCalled()
    })

    it('does not call `db.fetchPerson` if person not passed in', async () => {
        const event = { ...preIngestionEvent, person: existingPerson }

        const response = await emitToBufferStep(runner, event, () => false)

        expect(response).toEqual(['createEventStep', event])
        expect(runner.hub.db.fetchPerson).not.toHaveBeenCalled()
        expect(runner.hub.eventsProcessor.produceEventToBuffer).not.toHaveBeenCalled()
    })
})

describe('shouldSendEventToBuffer()', () => {
    beforeEach(() => {
        jest.spyOn(DateTime, 'now').mockReturnValue(now)
    })

    it('returns false for an existing non-anonymous person', () => {
        const result = shouldSendEventToBuffer(runner.hub, preIngestionEvent, existingPerson, 2)
        expect(result).toEqual(false)
    })

    it('returns true for recently created person', () => {
        const person = {
            ...existingPerson,
            created_at: now.minus({ seconds: 5 }),
        }

        const result = shouldSendEventToBuffer(runner.hub, preIngestionEvent, person, 2)
        expect(result).toEqual(true)
    })

    it('returns false for anonymous person', () => {
        const anonEvent = {
            ...preIngestionEvent,
            distinctId: '$some_device_id',
            properties: { $device_id: '$some_device_id' },
        }

        const result = shouldSendEventToBuffer(runner.hub, anonEvent, existingPerson, 2)
        expect(result).toEqual(false)
    })

    it('returns false for recently created anonymous person', () => {
        const anonEvent = {
            ...preIngestionEvent,
            distinctId: '$some_device_id',
            properties: { $device_id: '$some_device_id' },
        }

        const person = {
            ...existingPerson,
            created_at: now.minus({ seconds: 5 }),
        }

        const result = shouldSendEventToBuffer(runner.hub, anonEvent, person, 2)
        expect(result).toEqual(false)
    })

    it('returns true for non-existing person', () => {
        const result = shouldSendEventToBuffer(runner.hub, preIngestionEvent, undefined, 2)
        expect(result).toEqual(true)
    })

    it('returns false for $identify events for non-existing users', () => {
        const event = {
            ...preIngestionEvent,
            event: '$identify',
        }

        const result = shouldSendEventToBuffer(runner.hub, event, undefined, 2)
        expect(result).toEqual(false)
    })

    it('returns false for $identify events for new users', () => {
        const event = {
            ...preIngestionEvent,
            event: '$identify',
        }
        const person = {
            ...existingPerson,
            created_at: now.minus({ seconds: 5 }),
        }

        const result = shouldSendEventToBuffer(runner.hub, event, person, 2)
        expect(result).toEqual(false)
    })

    it('handles CONVERSION_BUFFER_ENABLED and conversionBufferEnabledTeams', () => {
        runner.hub.CONVERSION_BUFFER_ENABLED = false
        runner.hub.conversionBufferEnabledTeams = new Set([2])

        expect(shouldSendEventToBuffer(runner.hub, preIngestionEvent, undefined, 2)).toEqual(true)
        expect(shouldSendEventToBuffer(runner.hub, preIngestionEvent, undefined, 3)).toEqual(false)

        runner.hub.CONVERSION_BUFFER_ENABLED = true
        expect(shouldSendEventToBuffer(runner.hub, preIngestionEvent, undefined, 3)).toEqual(true)
    })
})
