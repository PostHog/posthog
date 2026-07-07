import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { useAIData } from '../hooks/useAIData'
import { ConversationDisplay } from './ConversationDisplay'

jest.mock('../hooks/useAIData', () => ({
    useAIData: jest.fn(),
}))

jest.mock('./ConversationMessagesDisplay', () => ({
    ConversationMessagesDisplay: jest.fn(() => null),
}))

jest.mock('./MetadataHeader', () => ({
    MetadataHeader: jest.fn(() => null),
}))

const mockUseAIData = useAIData as jest.MockedFunction<typeof useAIData>

describe('ConversationDisplay', () => {
    beforeEach(() => {
        initKeaTests()
        mockUseAIData.mockImplementation((eventData) => ({
            input: eventData?.input,
            output: eventData?.output,
            tools: eventData?.tools,
            isLoading: false,
        }))
    })

    afterEach(() => {
        cleanup()
        jest.resetAllMocks()
    })

    it.each([
        [
            '$ai_generation without $ai_input',
            '$ai_generation',
            {
                $ai_input_state: { messages: [{ type: 'system', content: 'state input' }] },
                $ai_output_choices: [{ message: { role: 'assistant', content: 'choice output' } }],
                $ai_output: 'plain output',
                $ai_tools: [{ function: { name: 'search' } }],
                $ai_trace_id: 'trace-1',
            },
            {
                input: undefined,
                output: [{ message: { role: 'assistant', content: 'choice output' } }],
            },
        ],
        [
            '$ai_generation with $ai_input',
            '$ai_generation',
            {
                $ai_input: [{ role: 'user', content: 'generation input' }],
                $ai_output: 'plain output',
                $ai_tools: [{ function: { name: 'search' } }],
                $ai_trace_id: 'trace-1',
            },
            {
                input: [{ role: 'user', content: 'generation input' }],
                output: 'plain output',
            },
        ],
        [
            '$ai_embedding',
            '$ai_embedding',
            {
                $ai_input: 'embedding input',
                $ai_output_state: 'state output',
                $ai_tools: [{ function: { name: 'search' } }],
                $ai_trace_id: 'trace-1',
            },
            {
                input: 'embedding input',
                output: 'Embedding vector generated',
            },
        ],
        [
            '$ai_span',
            '$ai_span',
            {
                $ai_input: [{ role: 'user', content: 'generation-like input' }],
                $ai_input_state: { messages: [{ type: 'human', content: 'state input' }] },
                $ai_output_choices: [{ message: { role: 'assistant', content: 'choice output' } }],
                $ai_output_state: { messages: [{ type: 'ai', content: 'state output' }] },
                $ai_tools: [{ function: { name: 'search' } }],
                $ai_trace_id: 'trace-1',
            },
            {
                input: { messages: [{ type: 'human', content: 'state input' }] },
                output: { messages: [{ type: 'ai', content: 'state output' }] },
            },
        ],
    ])('passes trace-view-compatible data for %s', (_label, eventName, eventProperties, expected) => {
        render(
            <Provider>
                <ConversationDisplay
                    eventProperties={eventProperties}
                    eventId="event-1"
                    eventName={eventName}
                    eventTimestamp="2026-07-06T20:22:00Z"
                />
            </Provider>
        )

        expect(mockUseAIData).toHaveBeenCalledWith({
            uuid: 'event-1',
            input: expected.input,
            output: expected.output,
            tools: [{ function: { name: 'search' } }],
            traceId: 'trace-1',
            timestamp: '2026-07-06T20:22:00Z',
        })
    })
})
