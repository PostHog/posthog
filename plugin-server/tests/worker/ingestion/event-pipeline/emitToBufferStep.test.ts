import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person } from '../../../../src/types'
import { UUIDT } from '../../../../src/utils/utils'
import {
    emitToBufferStep,
    shouldSendEventToBuffer,
} from '../../../../src/worker/ingestion/event-pipeline/1-emitToBufferStep'

const now = DateTime.fromISO('2020-01-01T12:00:05.200Z')

const pluginEvent: PluginEvent = {
    event: '$pageview',
    properties: { foo: 'bar' },
    timestamp: '2020-02-23T02:15:00Z',
    now: '2020-02-23T02:15:00Z',
    team_id: 2,
    distinct_id: 'my_id',
    ip: null,
    site_url: 'https://example.com',
    uuid: new UUIDT().toString(),
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
        const response = await emitToBufferStep(runner, pluginEvent, () => true)

        expect(runner.hub.eventsProcessor.produceEventToBuffer).toHaveBeenCalledWith(pluginEvent)
        expect(runner.hub.db.fetchPerson).toHaveBeenCalledWith(2, 'my_id')
        expect(response).toEqual(null)
    })

    it('calls `pluginsProcessEventStep` next if not buffering', async () => {
        const response = await emitToBufferStep(runner, pluginEvent, () => false)

        expect(response).toEqual(['pluginsProcessEventStep', pluginEvent, existingPerson])
        expect(runner.hub.db.fetchPerson).toHaveBeenCalledWith(2, 'my_id')
        expect(runner.hub.eventsProcessor.produceEventToBuffer).not.toHaveBeenCalled()
    })

    it('calls `processPersonsStep` for $snapshot events', async () => {
        const event = { ...pluginEvent, event: '$snapshot' }

        const response = await emitToBufferStep(runner, event, () => true)

        expect(response).toEqual(['processPersonsStep', event, undefined])
        expect(runner.hub.db.fetchPerson).not.toHaveBeenCalled()
        expect(runner.hub.eventsProcessor.produceEventToBuffer).not.toHaveBeenCalled()
    })
})

describe('shouldSendEventToBuffer()', () => {
    beforeEach(() => {
        jest.spyOn(DateTime, 'now').mockReturnValue(now)
    })

    it('returns false for an existing non-anonymous person', () => {
        const result = shouldSendEventToBuffer(runner.hub, pluginEvent, existingPerson, 2)
        expect(result).toEqual(false)
    })

    it('returns true for recently created person', () => {
        const person = {
            ...existingPerson,
            created_at: now.minus({ seconds: 5 }),
        }

        const result = shouldSendEventToBuffer(runner.hub, pluginEvent, person, 2)
        expect(result).toEqual(true)
    })

    it('returns false for anonymous person', () => {
        const anonEvent = {
            ...pluginEvent,
            distinctId: '$some_device_id',
            properties: { $device_id: '$some_device_id' },
        }

        const result = shouldSendEventToBuffer(runner.hub, anonEvent, existingPerson, 2)
        expect(result).toEqual(false)
    })

    it('returns false for recently created anonymous person', () => {
        const anonEvent = {
            ...pluginEvent,
            distinct_id: '$some_device_id',
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
        const result = shouldSendEventToBuffer(runner.hub, pluginEvent, undefined, 2)
        expect(result).toEqual(true)
    })

    it('returns false for $identify events for non-existing users', () => {
        const event = {
            ...pluginEvent,
            event: '$identify',
        }

        const result = shouldSendEventToBuffer(runner.hub, event, undefined, 2)
        expect(result).toEqual(false)
    })

    it('returns false for $identify events for new users', () => {
        const event = {
            ...pluginEvent,
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

        expect(shouldSendEventToBuffer(runner.hub, pluginEvent, undefined, 2)).toEqual(true)
        expect(shouldSendEventToBuffer(runner.hub, pluginEvent, undefined, 3)).toEqual(false)

        runner.hub.CONVERSION_BUFFER_ENABLED = true
        expect(shouldSendEventToBuffer(runner.hub, pluginEvent, undefined, 3)).toEqual(true)
    })
})
