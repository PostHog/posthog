import posthog from 'posthog-js'

import { resolveAiBlobUrl } from './aiBlob'
import { captureNormalizationFailure, normalizeMessage, normalizeMessages } from './messageNormalization'

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
            expect(result.messages[0]).toEqual({ role: 'available tools', content: '', tools: [{ name: 'search' }] })
        })

        it('normalizeMessages carries no message for nullish/scalar input', () => {
            expect(normalizeMessages(null, 'user').messages).toEqual([])
            expect(normalizeMessages(42, 'user').messages).toEqual([])
        })
    })

    describe('normalizeMessages recognition', () => {
        it('reports a recognized conversation alongside its messages', () => {
            expect(normalizeMessages({ role: 'assistant', content: 'hi' }, 'user')).toEqual({
                messages: [{ role: 'assistant', content: 'hi' }],
                recognized: true,
            })
        })

        it('reports opaque state as unrecognized and salvages it', () => {
            const result = normalizeMessages({ file_path: 'src/index.ts' }, 'user')
            expect(result.recognized).toBe(false)
            expect(result.messages).toHaveLength(1)
        })

        it("never captures — reporting a failure is the caller's decision", () => {
            normalizeMessages({ file_path: 'src/index.ts' }, 'user')
            expect(capture).not.toHaveBeenCalled()
        })
    })

    describe('offloaded media', () => {
        const HASH = 'a'.repeat(64)
        const POINTER = `phaiblob://v1/sha256/${HASH}?mime=image%2Fpng&size=332378`

        it('keeps an offloaded anthropic tool_result image resolvable through the blob endpoint', () => {
            const { messages } = normalizeMessages(
                {
                    role: 'user',
                    content: [
                        {
                            type: 'tool_result',
                            tool_use_id: 'toolu_01Rg4FtbD8eH1fx2yMkQGVSz',
                            content: [
                                {
                                    type: 'image',
                                    source: { type: 'base64', media_type: 'image/png', data: POINTER },
                                },
                            ],
                        },
                    ],
                },
                'user'
            )

            const images = messages
                .flatMap((message) => (Array.isArray(message.content) ? message.content : []))
                .flatMap((part) => (typeof part === 'object' && 'image' in part ? [part.image] : []))

            expect(images).toHaveLength(1)
            expect(resolveAiBlobUrl(images[0], 1)).toBe(`/api/projects/1/ai_blob/v1/sha256/${HASH}`)
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
