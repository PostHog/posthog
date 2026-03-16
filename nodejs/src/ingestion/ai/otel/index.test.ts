import { aiOtelEventTypeCounter, aiOtelMiddlewareCounter } from '../metrics'
import { mapOtelAttributes } from './attribute-mapping'
import { convertOtelEvent } from './index'
import { createEvent } from './test-helpers'

jest.mock('../metrics', () => ({
    aiOtelMiddlewareCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    aiOtelEventTypeCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
}))

jest.mock('./attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

const mockedMapOtelAttributes = jest.mocked(mapOtelAttributes)
const mockedMiddlewareCounter = jest.mocked(aiOtelMiddlewareCounter)
const mockedEventTypeCounter = jest.mocked(aiOtelEventTypeCounter)

describe('convertOtelEvent', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('library detection', () => {
        it.each([
            ['no library markers', {}],
            ['only gen_ai.system', { 'gen_ai.system': 'openai' }],
            ['only gen_ai.provider.name', { 'gen_ai.provider.name': 'anthropic' }],
        ])('runs general mapping directly when %s', (_label, properties) => {
            const event = createEvent('$ai_generation', properties)
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it.each([
            ['pydantic_ai.all_messages', { 'pydantic_ai.all_messages': '[]' }],
            ['logfire.msg', { 'logfire.msg': 'running 1 tool' }],
            ['logfire.json_schema', { 'logfire.json_schema': '{}' }],
            ['model_request_parameters', { model_request_parameters: '{}' }],
        ])('detects pydantic-ai library from %s attribute', (_label, properties) => {
            const event = createEvent('$ai_span', properties)
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it('detects pydantic-ai even when gen_ai.system is set to a different provider', () => {
            const event = createEvent('$ai_generation', {
                'gen_ai.system': 'openai',
                'logfire.json_schema': '{}',
            })
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
            expect(event.properties!['logfire.json_schema']).toBeUndefined()
        })

        it.each([
            ['ai.operationId', { 'ai.operationId': 'ai.generateText.doGenerate' }],
            ['ai.telemetry.functionId', { 'ai.telemetry.functionId': 'my-function' }],
        ])('detects vercel-ai library from %s attribute', (_label, properties) => {
            const event = createEvent('$ai_generation', properties)
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
            expect(event.properties!['$ai_lib']).toBe('opentelemetry/vercel-ai')
        })

        it('prefers pydantic-ai detection over vercel-ai when both markers present', () => {
            const event = createEvent('$ai_generation', {
                'logfire.msg': 'test',
                'ai.operationId': 'ai.generateText.doGenerate',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_lib']).toBe('opentelemetry/pydantic-ai')
        })
    })

    describe('metrics', () => {
        it('increments middleware counter with library name when matched', () => {
            const event = createEvent('$ai_generation', { 'logfire.msg': 'test' })
            convertOtelEvent(event)
            expect(mockedMiddlewareCounter.labels).toHaveBeenCalledWith({ library: 'pydantic-ai' })
        })

        it('increments middleware counter with "none" when no middleware matches', () => {
            const event = createEvent('$ai_generation', {})
            convertOtelEvent(event)
            expect(mockedMiddlewareCounter.labels).toHaveBeenCalledWith({ library: 'none' })
        })

        it('increments event type counter with event type and library', () => {
            const event = createEvent('$ai_generation', { 'ai.operationId': 'ai.generateText.doGenerate' })
            convertOtelEvent(event)
            expect(mockedEventTypeCounter.labels).toHaveBeenCalledWith({
                event_type: '$ai_generation',
                library: 'vercel-ai',
            })
        })
    })
})
