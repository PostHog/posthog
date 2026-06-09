import posthog from 'posthog-js'

import {
    captureNormalizationFailure,
    normalizeConversation,
    normalizeMessage,
    normalizeMessages,
} from './messageNormalization'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))

const capture = jest.mocked(posthog.capture)

describe('messageNormalization', () => {
    beforeEach(() => jest.clearAllMocks())

    describe('delegates to the recipe normalizer', () => {
        it('normalizeMessage normalizes a single message', () => {
            expect(normalizeMessage({ role: 'assistant', content: 'hi' }, 'user')).toEqual([
                { role: 'assistant', content: 'hi' },
            ])
        })

        it('normalizeMessages prepends an available-tools pseudo-message when tools are passed', () => {
            const result = normalizeMessages({ role: 'user', content: 'hi' }, 'user', [{ name: 'search' }])
            expect(result[0]).toEqual({ role: 'available tools', content: '', tools: [{ name: 'search' }] })
        })

        it('normalizeMessages carries no message for nullish/scalar input', () => {
            expect(normalizeMessages(null, 'user')).toEqual([])
            expect(normalizeMessages(42, 'user')).toEqual([])
        })
    })

    describe('normalizeConversation', () => {
        it('reports a recognized conversation alongside its messages', () => {
            expect(normalizeConversation({ role: 'assistant', content: 'hi' }, 'user')).toEqual({
                messages: [{ role: 'assistant', content: 'hi' }],
                recognized: true,
            })
        })

        it('reports opaque state as unrecognized and salvages it', () => {
            const result = normalizeConversation({ file_path: 'src/index.ts' }, 'user')
            expect(result.recognized).toBe(false)
            expect(result.messages).toHaveLength(1)
        })

        it("never captures — reporting a failure is the caller's decision", () => {
            normalizeConversation({ file_path: 'src/index.ts' }, 'user')
            expect(capture).not.toHaveBeenCalled()
        })
    })

    describe('captureNormalizationFailure', () => {
        it('reports an object payload with its keys and type', () => {
            captureNormalizationFailure({ file_path: 'src/index.ts' })
            expect(capture).toHaveBeenCalledWith('llma message normalization failed', {
                message_keys: ['file_path'],
                message_type: 'object',
            })
        })

        it('reports a scalar payload with no keys', () => {
            captureNormalizationFailure('opaque')
            expect(capture).toHaveBeenCalledWith('llma message normalization failed', {
                message_keys: [],
                message_type: 'string',
            })
        })
    })
})
