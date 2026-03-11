import { PluginEvent } from '~/plugin-scaffold'

import { mapOtelAttributes } from './attribute-mapping'
import { convertOtelEvent } from './index'

jest.mock('./attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

const mockedMapOtelAttributes = jest.mocked(mapOtelAttributes)

const createEvent = (event: string, properties: Record<string, unknown>): PluginEvent => ({
    event,
    distinct_id: 'user-123',
    team_id: 1,
    properties,
    uuid: 'test-uuid',
    timestamp: new Date().toISOString(),
    ip: '127.0.0.1',
    site_url: 'https://app.posthog.com',
    now: new Date().toISOString(),
})

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
})
