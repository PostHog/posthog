import { v4 } from 'uuid'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService, TransformationResult } from '../../cdp/hog-transformations/hog-transformer.service'
import { PipelineResultType, isDropResult, isOkResult } from '../pipelines/results'
import { HogTransformEventInput, createHogTransformEventStep } from './hog-transform-event-step'

const createTestInput = (): HogTransformEventInput => {
    return {
        event: {
            uuid: v4(),
            event: '$pageview',
            distinct_id: 'user-1',
            properties: { $current_url: 'https://example.com' },
            now: new Date().toISOString(),
        },
        team: {
            id: 1,
        },
    } as unknown as HogTransformEventInput
}

const createMockHogTransformer = (transformFn: (event: PluginEvent) => TransformationResult): HogTransformerService => {
    return {
        transformEventAndProduceMessages: jest.fn(transformFn),
    } as unknown as HogTransformerService
}

describe('createHogTransformEventStep', () => {
    it('passes through unchanged when no transformer configured', async () => {
        const hogTransformEventStep = createHogTransformEventStep(null)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(isOkResult(result) && result.value).toBe(input)
    })

    it('passes through unchanged when transformer returns same event', async () => {
        const mockTransformer = createMockHogTransformer((event) => ({
            event,
            invocationResults: [],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockTransformer.transformEventAndProduceMessages).toHaveBeenCalledWith(input.event)
    })

    it('drops event when transformation returns null', async () => {
        const mockTransformer = createMockHogTransformer(() => ({
            event: null,
            invocationResults: [],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        expect(isDropResult(result) && result.reason).toBe('dropped_by_transformation')
    })

    it('returns transformed event with modified properties', async () => {
        const mockTransformer = createMockHogTransformer((event) => ({
            event: {
                ...event,
                properties: { ...event.properties, transformed: true },
            },
            invocationResults: [],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.properties).toMatchObject({
                $current_url: 'https://example.com',
                transformed: true,
            })
        }
    })

    it('returns transformed event with modified event name', async () => {
        const mockTransformer = createMockHogTransformer((event) => ({
            event: {
                ...event,
                event: 'custom_event',
            },
            invocationResults: [],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.event).toBe('custom_event')
        }
    })

    it('returns transformed event with modified distinct_id', async () => {
        const mockTransformer = createMockHogTransformer((event) => ({
            event: {
                ...event,
                distinct_id: 'new-user-id',
            },
            invocationResults: [],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.distinct_id).toBe('new-user-id')
        }
    })
})
