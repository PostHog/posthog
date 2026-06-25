import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { useAIData } from '../hooks/useAIData'
import { EventContentConversation } from './EventContentWithAsyncData'

jest.mock('../customParser/useCustomParserMaxTool', () => ({
    useCustomParserMaxTool: jest.fn(() => null),
}))

jest.mock('../hooks/useAIData', () => ({
    useAIData: jest.fn(),
}))

const mockUseAIData = useAIData as jest.MockedFunction<typeof useAIData>

describe('EventContentConversation', () => {
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

    it('passes trace coordinates to the AI data loader', () => {
        const rawInput = [{ role: 'user', content: 'hi' }]
        const rawOutput = [{ role: 'assistant', content: 'hello' }]
        const tools = [{ function: { name: 'search' } }]

        render(
            <Provider>
                <EventContentConversation
                    eventId="event-1"
                    traceId="trace-1"
                    timestamp="2026-06-23T10:00:00Z"
                    rawInput={rawInput}
                    rawOutput={rawOutput}
                    tools={tools}
                />
            </Provider>
        )

        expect(mockUseAIData).toHaveBeenCalledWith({
            uuid: 'event-1',
            input: rawInput,
            output: rawOutput,
            tools,
            traceId: 'trace-1',
            timestamp: '2026-06-23T10:00:00Z',
        })
    })
})
