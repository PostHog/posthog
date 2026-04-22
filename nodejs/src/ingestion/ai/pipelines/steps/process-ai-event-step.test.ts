import { PluginEvent } from '~/plugin-scaffold'

import { captureException } from '../../../../utils/posthog'
import { UUIDT } from '../../../../utils/utils'
import { PipelineResultType } from '../../../pipelines/results'
import { processAiEvent } from '../../process-ai-event'
import { createProcessAiEventStep } from './process-ai-event-step'

jest.mock('../../../../utils/posthog', () => ({
    captureException: jest.fn(),
}))

jest.mock('../../process-ai-event', () => {
    const actual = jest.requireActual('../../process-ai-event')
    return {
        AI_EVENT_TYPES: actual.AI_EVENT_TYPES,
        processAiEvent: jest.fn((event: PluginEvent) => ({
            ...event,
            properties: { ...event.properties, $ai_was_processed: true },
        })),
    }
})

const mockedProcessAiEvent = processAiEvent as jest.MockedFunction<typeof processAiEvent>
const mockedCaptureException = captureException as jest.MockedFunction<typeof captureException>

function createTestEvent(overrides: Partial<PluginEvent> = {}): PluginEvent {
    return {
        distinct_id: 'user-1',
        ip: null,
        site_url: 'http://localhost',
        team_id: 1,
        now: '2020-02-23T02:15:00Z',
        timestamp: '2020-02-23T02:15:00Z',
        event: '$pageview',
        uuid: new UUIDT().toString(),
        properties: {},
        ...overrides,
    }
}

describe('processAiEventStep', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([
        '$ai_generation',
        '$ai_embedding',
        '$ai_evaluation',
        '$ai_span',
        '$ai_trace',
        '$ai_metric',
        '$ai_feedback',
    ])('calls processAiEvent for %s event', async (eventName) => {
        const event = createTestEvent({ event: eventName, properties: { $ai_model: 'gpt-4' } })
        const step = createProcessAiEventStep()
        const input = { normalizedEvent: event }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockedProcessAiEvent).toHaveBeenCalledWith(event)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties?.$ai_was_processed).toBe(true)
        }
    })

    it.each(['$pageview', '$autocapture', 'custom_event', '$$heatmap'])('sends %s event to DLQ', async (eventName) => {
        const event = createTestEvent({ event: eventName })
        const step = createProcessAiEventStep()
        const input = { normalizedEvent: event }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        expect(mockedProcessAiEvent).not.toHaveBeenCalled()
    })

    it('passes through unchanged on processAiEvent error', async () => {
        const event = createTestEvent({ event: '$ai_generation' })
        mockedProcessAiEvent.mockImplementationOnce(() => {
            throw new Error('cost calculation failed')
        })

        const step = createProcessAiEventStep()
        const input = { normalizedEvent: event }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockedCaptureException).toHaveBeenCalled()
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent).toBe(event)
        }
    })

    it('preserves additional input fields', async () => {
        const event = createTestEvent({ event: '$ai_generation' })
        const step = createProcessAiEventStep<{ normalizedEvent: PluginEvent; extraField: string }>()
        const input = { normalizedEvent: event, extraField: 'preserved' }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.extraField).toBe('preserved')
        }
    })
})
