import { PluginEvent } from '~/plugin-scaffold'

import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { HogTransformerService, TransformationResult } from '../../cdp/hog-transformations/hog-transformer.service'
import { PipelineResultType, isDropResult, isOkResult } from '../pipelines/results'
import { HogTransformEventInput, createHogTransformEventStep } from './hog-transform-event-step'

type MockHogTransformer = Pick<HogTransformerService, 'transformEventAndProduceMessages'>

const createTestInput = (): HogTransformEventInput => {
    return {
        event: createTestPluginEvent({
            event: '$pageview',
            distinct_id: 'user-1',
            properties: { $current_url: 'https://example.com' },
        }),
        team: createTestTeam(),
    }
}

const createMockHogTransformer = (transformFn: (event: PluginEvent) => TransformationResult): MockHogTransformer => {
    return {
        transformEventAndProduceMessages: jest.fn((event) => Promise.resolve(transformFn(event))),
    }
}

describe('createHogTransformEventStep', () => {
    it('passes through unchanged when no transformer configured', async () => {
        const hogTransformEventStep = createHogTransformEventStep(null)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event).toBe(input.event)
            expect(result.value.transformationsRun).toBe(0)
        }
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
        if (isOkResult(result)) {
            expect(result.value.transformationsRun).toBe(0)
        }
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
            invocationResults: [{} as any],
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
            expect(result.value.transformationsRun).toBe(1)
        }
    })

    it('returns transformed event with modified event name', async () => {
        const mockTransformer = createMockHogTransformer((event) => ({
            event: {
                ...event,
                event: 'custom_event',
            },
            invocationResults: [{} as any],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.event).toBe('custom_event')
            expect(result.value.transformationsRun).toBe(1)
        }
    })

    it('returns transformed event with modified distinct_id', async () => {
        const mockTransformer = createMockHogTransformer((event) => ({
            event: {
                ...event,
                distinct_id: 'new-user-id',
            },
            invocationResults: [{} as any],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.event.distinct_id).toBe('new-user-id')
            expect(result.value.transformationsRun).toBe(1)
        }
    })

    it('counts multiple invocation results', async () => {
        const mockTransformer = createMockHogTransformer((event) => ({
            event,
            invocationResults: [{} as any, {} as any, {} as any],
        }))
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        const result = await hogTransformEventStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (isOkResult(result)) {
            expect(result.value.transformationsRun).toBe(3)
        }
    })

    it('rethrows exceptions from the transformer', async () => {
        const mockTransformer: MockHogTransformer = {
            transformEventAndProduceMessages: jest.fn().mockRejectedValue(new Error('transformer broke')),
        }
        const hogTransformEventStep = createHogTransformEventStep(mockTransformer)
        const input = createTestInput()

        await expect(hogTransformEventStep(input)).rejects.toThrow('transformer broke')
    })
})
