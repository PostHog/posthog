import { setUsageInNonPersonEventsCounter } from '../../main/ingestion-queues/metrics'
import { PipelineEvent } from '../../types'
import { PerDistinctIdPipelineInput } from '../ingestion-consumer'
import { PipelineResultType } from '../pipelines/results'
import { createTrackNonPersonEventUpdatesStep } from './track-non-person-event-updates-step'

jest.mock('../../main/ingestion-queues/metrics', () => ({
    setUsageInNonPersonEventsCounter: {
        inc: jest.fn(),
    },
}))

describe('createTrackNonPersonEventUpdatesStep', () => {
    const createMockEvent = (event: Partial<PipelineEvent>): PerDistinctIdPipelineInput => ({
        event: {
            event: event.event || '$pageview',
            distinct_id: event.distinct_id || 'user1',
            properties: event.properties || {},
            ...event,
        } as PipelineEvent,
        team: { id: 1 } as any,
        message: {} as any,
        headers: {} as any,
        personsStoreForBatch: {} as any,
        groupStoreForBatch: {} as any,
    })

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('should return all events as ok', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [createMockEvent({ event: '$pageview' }), createMockEvent({ event: '$autocapture' })]

        const results = await step(events)

        expect(results).toHaveLength(2)
        results.forEach((result) => {
            expect(result.type).toBe(PipelineResultType.OK)
        })
    })

    it('should not increment counter for person events', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: '$set',
                properties: { $set: { foo: 'bar' } },
            }),
            createMockEvent({
                event: '$identify',
                properties: { $set: { foo: 'bar' } },
            }),
        ]

        await step(events)

        expect(setUsageInNonPersonEventsCounter.inc).not.toHaveBeenCalled()
    })

    it('should not increment counter for known set events', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: '$feature_interaction',
                properties: { $set: { foo: 'bar' } },
            }),
            createMockEvent({
                event: 'survey dismissed',
                properties: { $set_once: { foo: 'bar' } },
            }),
        ]

        await step(events)

        expect(setUsageInNonPersonEventsCounter.inc).not.toHaveBeenCalled()
    })

    it('should not increment counter for events without $set/$set_once/$unset', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: '$pageview',
                properties: { foo: 'bar' },
            }),
            createMockEvent({
                event: 'custom_event',
                properties: { baz: 'qux' },
            }),
        ]

        await step(events)

        expect(setUsageInNonPersonEventsCounter.inc).not.toHaveBeenCalled()
    })

    it('should increment counter for non-person events with $set', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: '$pageview',
                properties: { $set: { foo: 'bar' } },
            }),
        ]

        await step(events)

        expect(setUsageInNonPersonEventsCounter.inc).toHaveBeenCalledTimes(1)
    })

    it('should increment counter for non-person events with $set_once', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: 'custom_event',
                properties: { $set_once: { foo: 'bar' } },
            }),
        ]

        await step(events)

        expect(setUsageInNonPersonEventsCounter.inc).toHaveBeenCalledTimes(1)
    })

    it('should increment counter for non-person events with $unset', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: 'custom_event',
                properties: { $unset: ['foo'] },
            }),
        ]

        await step(events)

        expect(setUsageInNonPersonEventsCounter.inc).toHaveBeenCalledTimes(1)
    })

    it('should increment counter multiple times for batch with multiple matching events', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: '$pageview',
                properties: { $set: { foo: 'bar' } },
            }),
            createMockEvent({
                event: 'custom_event',
                properties: { $set_once: { baz: 'qux' } },
            }),
            createMockEvent({
                event: 'another_event',
                properties: { $unset: ['old'] },
            }),
        ]

        await step(events)

        expect(setUsageInNonPersonEventsCounter.inc).toHaveBeenCalledTimes(3)
    })

    it('should handle mixed batch with some matching and some non-matching events', async () => {
        const step = createTrackNonPersonEventUpdatesStep()
        const events = [
            createMockEvent({
                event: '$pageview',
                properties: { $set: { foo: 'bar' } },
            }),
            createMockEvent({
                event: '$identify',
                properties: { $set: { foo: 'bar' } },
            }),
            createMockEvent({
                event: 'custom_event',
                properties: { regular: 'prop' },
            }),
            createMockEvent({
                event: 'another_event',
                properties: { $set_once: { baz: 'qux' } },
            }),
        ]

        await step(events)

        // Only first and last events should increment
        expect(setUsageInNonPersonEventsCounter.inc).toHaveBeenCalledTimes(2)
    })
})
