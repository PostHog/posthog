import { aiCostModalityExtractionCounter } from '../metrics'
import { extractModalityTokens } from './modality-tokens'
import { createAIEvent } from './test-helpers'

describe('extractModalityTokens()', () => {
    describe('Gemini direct usage metadata', () => {
        it('extracts image and text tokens from candidatesTokensDetails array format', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 100,
                    candidatesTokenCount: 1300,
                    candidatesTokensDetails: [
                        { modality: 'TEXT', tokenCount: 10 },
                        { modality: 'IMAGE', tokenCount: 1290 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts image and text tokens from candidatesTokensDetails object format (fallback)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 100,
                    candidatesTokenCount: 1300,
                    candidatesTokensDetails: {
                        textTokens: 10,
                        imageTokens: 1290,
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts image and text tokens from outputTokenDetails array format', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 100,
                    candidatesTokenCount: 1300,
                    outputTokenDetails: [
                        { modality: 'TEXT', tokenCount: 10 },
                        { modality: 'IMAGE', tokenCount: 1290 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts image and text tokens from outputTokenDetails object format (fallback)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 100,
                    candidatesTokenCount: 1300,
                    outputTokenDetails: {
                        textTokens: 10,
                        imageTokens: 1290,
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('does not set image tokens when zero (array format)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    candidatesTokensDetails: [
                        { modality: 'TEXT', tokenCount: 100 },
                        { modality: 'IMAGE', tokenCount: 0 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBe(100)
        })

        it('does not set image tokens when zero (object format)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    candidatesTokensDetails: {
                        textTokens: 100,
                        imageTokens: 0,
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBe(100)
        })

        it('handles missing token details', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 100,
                    candidatesTokenCount: 500,
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('handles case-insensitive modality values (backward compatibility)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    candidatesTokensDetails: [
                        { modality: 'text', tokenCount: 10 },
                        { modality: 'image', tokenCount: 1290 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
        })

        it('handles mixed case modality values', () => {
            const event = createAIEvent({
                $ai_usage: {
                    candidatesTokensDetails: [
                        { modality: 'Text', tokenCount: 10 },
                        { modality: 'Image', tokenCount: 1290 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
        })
    })

    describe('Vercel AI SDK structure', () => {
        it('extracts tokens from providerMetadata.google structure (array format)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    usage: {
                        inputTokens: 100,
                        outputTokens: 1300,
                    },
                    providerMetadata: {
                        google: {
                            candidatesTokensDetails: [
                                { modality: 'text', tokenCount: 10 },
                                { modality: 'image', tokenCount: 1290 },
                            ],
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts tokens from providerMetadata.google structure (object format fallback)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    usage: {
                        inputTokens: 100,
                        outputTokens: 1300,
                    },
                    providerMetadata: {
                        google: {
                            candidatesTokensDetails: {
                                textTokens: 10,
                                imageTokens: 1290,
                            },
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts tokens from providerMetadata.google.outputTokenDetails (array format)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    usage: {
                        inputTokens: 100,
                        outputTokens: 1300,
                    },
                    providerMetadata: {
                        google: {
                            outputTokenDetails: [
                                { modality: 'text', tokenCount: 10 },
                                { modality: 'image', tokenCount: 1290 },
                            ],
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts tokens from providerMetadata.google.outputTokenDetails (object format fallback)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    usage: {
                        inputTokens: 100,
                        outputTokens: 1300,
                    },
                    providerMetadata: {
                        google: {
                            outputTokenDetails: {
                                textTokens: 10,
                                imageTokens: 1290,
                            },
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
        })

        it('handles non-google provider metadata', () => {
            const event = createAIEvent({
                $ai_usage: {
                    usage: {
                        inputTokens: 100,
                        outputTokens: 500,
                    },
                    providerMetadata: {
                        openai: {
                            someOtherField: 'value',
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts tokens from Vercel AI SDK V3 structure (rawUsage.usage.raw)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    rawUsage: {
                        usage: {
                            inputTokens: { total: 11, noCache: 11, cacheRead: 0 },
                            outputTokens: { total: 1304, text: 1304, reasoning: 0 },
                            raw: {
                                promptTokenCount: 11,
                                candidatesTokenCount: 1304,
                                totalTokenCount: 1315,
                                candidatesTokensDetails: [{ modality: 'IMAGE', tokenCount: 1290 }],
                            },
                        },
                        providerMetadata: {
                            google: {
                                usageMetadata: {
                                    promptTokenCount: 11,
                                    candidatesTokenCount: 1304,
                                    totalTokenCount: 1315,
                                },
                            },
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts tokens from Vercel AI SDK with rawResponse (rawUsage.rawResponse.usageMetadata)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    rawUsage: {
                        usage: {
                            inputTokens: { total: 11, noCache: 11, cacheRead: 0 },
                            outputTokens: { total: 1301, text: 1301, reasoning: 0 },
                        },
                        providerMetadata: {
                            google: {
                                usageMetadata: {
                                    promptTokenCount: 11,
                                    candidatesTokenCount: 1301,
                                    totalTokenCount: 1312,
                                },
                            },
                        },
                        rawResponse: {
                            usageMetadata: {
                                promptTokenCount: 11,
                                candidatesTokenCount: 1301,
                                totalTokenCount: 1312,
                                candidatesTokensDetails: [{ modality: 'IMAGE', tokenCount: 1290 }],
                            },
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })
    })

    describe('edge cases', () => {
        it('returns event unchanged when $ai_usage is undefined', () => {
            const event = createAIEvent({
                $ai_model: 'gpt-4',
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBeUndefined()
        })

        it('returns event unchanged when $ai_usage is null', () => {
            const event = createAIEvent({
                $ai_usage: null,
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBeUndefined()
        })

        it('returns event unchanged when $ai_usage is not an object', () => {
            const event = createAIEvent({
                $ai_usage: 'some string',
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBeUndefined()
        })

        it('handles non-numeric imageTokens gracefully', () => {
            const event = createAIEvent({
                $ai_usage: {
                    candidatesTokensDetails: {
                        textTokens: 10,
                        imageTokens: 'not a number',
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_output_tokens']).toBe(10)
        })

        it('handles non-numeric textTokens gracefully', () => {
            const event = createAIEvent({
                $ai_usage: {
                    candidatesTokensDetails: {
                        textTokens: 'not a number',
                        imageTokens: 1290,
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
            expect(result.properties['$ai_text_output_tokens']).toBeUndefined()
        })

        it('always removes $ai_usage from properties', () => {
            const event = createAIEvent({
                $ai_usage: {
                    some: 'data',
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_usage']).toBeUndefined()
        })
    })

    describe('cache modality extraction', () => {
        it('extracts cached audio tokens from Gemini cacheTokensDetails array format', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 1000,
                    cachedContentTokenCount: 300,
                    cacheTokensDetails: [
                        { modality: 'TEXT', tokenCount: 250 },
                        { modality: 'AUDIO', tokenCount: 50 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBe(50)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts cached audio from Gemini cacheTokensDetails object format (defensive)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 1000,
                    cacheTokensDetails: { audioTokens: 50 },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBe(50)
        })

        it('does not set $ai_cache_read_audio_tokens when cacheTokensDetails has no audio entry', () => {
            const event = createAIEvent({
                $ai_usage: {
                    cacheTokensDetails: [{ modality: 'TEXT', tokenCount: 300 }],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBeUndefined()
        })

        it('extracts cached audio from OpenAI prompt_tokens_details.cached_tokens_details', () => {
            const event = createAIEvent({
                $ai_usage: {
                    prompt_tokens: 1000,
                    prompt_tokens_details: {
                        cached_tokens: 300,
                        audio_tokens: 200,
                        cached_tokens_details: {
                            audio_tokens: 50,
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBe(50)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('does not set $ai_cache_read_audio_tokens when OpenAI cached_tokens_details has no audio', () => {
            const event = createAIEvent({
                $ai_usage: {
                    prompt_tokens: 1000,
                    prompt_tokens_details: {
                        cached_tokens: 300,
                        cached_tokens_details: { text_tokens: 300 },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBeUndefined()
        })

        it('extracts cached audio from Vercel-wrapped Gemini metadata', () => {
            const event = createAIEvent({
                $ai_usage: {
                    rawResponse: {
                        usageMetadata: {
                            cacheTokensDetails: [{ modality: 'AUDIO', tokenCount: 100 }],
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBe(100)
        })

        it('ignores zero or negative cached audio counts', () => {
            const event = createAIEvent({
                $ai_usage: {
                    cacheTokensDetails: [{ modality: 'AUDIO', tokenCount: 0 }],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBeUndefined()
        })
    })

    describe('input modality extraction', () => {
        it('extracts audio + text input tokens from Gemini promptTokensDetails array format', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokenCount: 200,
                    promptTokensDetails: [
                        { modality: 'AUDIO', tokenCount: 120 },
                        { modality: 'TEXT', tokenCount: 80 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(120)
            expect(result.properties['$ai_text_input_tokens']).toBe(80)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts image + text input tokens from Gemini promptTokensDetails', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokensDetails: [
                        { modality: 'IMAGE', tokenCount: 400 },
                        { modality: 'TEXT', tokenCount: 50 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_image_input_tokens']).toBe(400)
            expect(result.properties['$ai_text_input_tokens']).toBe(50)
        })

        it('extracts input modality from object format (defensive fallback)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokensDetails: { audioTokens: 120, textTokens: 80 },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(120)
            expect(result.properties['$ai_text_input_tokens']).toBe(80)
        })

        it('handles case-insensitive Gemini modality values', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokensDetails: [
                        { modality: 'audio', tokenCount: 120 },
                        { modality: 'Text', tokenCount: 80 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(120)
            expect(result.properties['$ai_text_input_tokens']).toBe(80)
        })

        it('does not set audio input when token count is zero', () => {
            const event = createAIEvent({
                $ai_usage: {
                    promptTokensDetails: [
                        { modality: 'AUDIO', tokenCount: 0 },
                        { modality: 'TEXT', tokenCount: 100 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBeUndefined()
            expect(result.properties['$ai_text_input_tokens']).toBe(100)
        })

        it('extracts input modality from Vercel-wrapped Gemini metadata', () => {
            const event = createAIEvent({
                $ai_usage: {
                    rawResponse: {
                        usageMetadata: {
                            promptTokensDetails: [{ modality: 'AUDIO', tokenCount: 120 }],
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(120)
        })

        it('extracts input modality from providerMetadata.google', () => {
            const event = createAIEvent({
                $ai_usage: {
                    providerMetadata: {
                        google: {
                            promptTokensDetails: [{ modality: 'AUDIO', tokenCount: 120 }],
                        },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(120)
        })

        it('extracts total prompt audio from OpenAI prompt_tokens_details.audio_tokens', () => {
            const event = createAIEvent({
                $ai_usage: {
                    prompt_tokens: 300,
                    prompt_tokens_details: {
                        audio_tokens: 200, // total audio in prompt (cached + uncached)
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(200)
        })

        it('extracts both total and cached audio from OpenAI prompt_tokens_details', () => {
            const event = createAIEvent({
                $ai_usage: {
                    prompt_tokens: 300,
                    prompt_tokens_details: {
                        audio_tokens: 200,
                        cached_tokens_details: { audio_tokens: 50 },
                    },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(200)
            expect(result.properties['$ai_cache_read_audio_tokens']).toBe(50)
        })

        it('does not set audio input when OpenAI prompt audio_tokens is zero', () => {
            const event = createAIEvent({
                $ai_usage: {
                    prompt_tokens_details: { audio_tokens: 0 },
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBeUndefined()
        })
    })

    describe('snake_case Gemini metadata (posthog-python shape)', () => {
        // posthog-python forwards Gemini's protobuf usage_metadata via to_dict()
        // / vars(), which produces snake_case keys (prompt_tokens_details with
        // modality/token_count entries). Production traces from Python users
        // use this shape exclusively; the camelCase shape comes from the Vercel
        // AI SDK on Node.js.

        it('extracts audio + text input from snake_case prompt_tokens_details', () => {
            const event = createAIEvent({
                $ai_usage: {
                    prompt_token_count: 1348,
                    prompt_tokens_details: [
                        { modality: 'AUDIO', token_count: 750 },
                        { modality: 'TEXT', token_count: 598 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(750)
            expect(result.properties['$ai_text_input_tokens']).toBe(598)
            expect(result.properties['$ai_usage']).toBeUndefined()
        })

        it('extracts output modality from snake_case candidates_tokens_details', () => {
            const event = createAIEvent({
                $ai_usage: {
                    candidates_tokens_details: [
                        { modality: 'TEXT', token_count: 100 },
                        { modality: 'IMAGE', token_count: 1290 },
                    ],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_text_output_tokens']).toBe(100)
            expect(result.properties['$ai_image_output_tokens']).toBe(1290)
        })

        it('extracts cached audio from snake_case cache_tokens_details', () => {
            const event = createAIEvent({
                $ai_usage: {
                    cache_tokens_details: [{ modality: 'AUDIO', token_count: 50 }],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_cache_read_audio_tokens']).toBe(50)
        })

        it('handles snake_case input + output + cache together (full Gemini event)', () => {
            const event = createAIEvent({
                $ai_usage: {
                    prompt_token_count: 1348,
                    candidates_token_count: 100,
                    cached_content_token_count: 50,
                    prompt_tokens_details: [
                        { modality: 'AUDIO', token_count: 750 },
                        { modality: 'TEXT', token_count: 598 },
                    ],
                    candidates_tokens_details: [{ modality: 'TEXT', token_count: 100 }],
                    cache_tokens_details: [{ modality: 'AUDIO', token_count: 50 }],
                },
            })

            const result = extractModalityTokens(event)

            expect(result.properties['$ai_audio_input_tokens']).toBe(750)
            expect(result.properties['$ai_text_input_tokens']).toBe(598)
            expect(result.properties['$ai_text_output_tokens']).toBe(100)
            expect(result.properties['$ai_cache_read_audio_tokens']).toBe(50)
        })
    })

    describe('extraction counter labels', () => {
        const labelsSpy = jest.spyOn(aiCostModalityExtractionCounter, 'labels')

        beforeEach(() => {
            labelsSpy.mockClear()
        })

        afterAll(() => {
            labelsSpy.mockRestore()
        })

        it('emits status=no_details, source=none when nothing extracts', () => {
            extractModalityTokens(createAIEvent({ $ai_usage: { candidatesTokenCount: 100 } }))

            expect(labelsSpy).toHaveBeenCalledTimes(1)
            expect(labelsSpy).toHaveBeenCalledWith({ status: 'no_details', source: 'none' })
        })

        it('emits source=gemini_output for output-only extractions', () => {
            extractModalityTokens(
                createAIEvent({
                    $ai_usage: {
                        candidatesTokensDetails: [{ modality: 'IMAGE', tokenCount: 1290 }],
                    },
                })
            )

            expect(labelsSpy).toHaveBeenCalledTimes(1)
            expect(labelsSpy).toHaveBeenCalledWith({ status: 'extracted', source: 'gemini_output' })
        })

        it('emits source=gemini_cache for cache-only Gemini extractions', () => {
            extractModalityTokens(
                createAIEvent({
                    $ai_usage: {
                        cacheTokensDetails: [{ modality: 'AUDIO', tokenCount: 50 }],
                    },
                })
            )

            expect(labelsSpy).toHaveBeenCalledTimes(1)
            expect(labelsSpy).toHaveBeenCalledWith({ status: 'extracted', source: 'gemini_cache' })
        })

        it('emits source=openai_cache for OpenAI cached_tokens_details extractions', () => {
            extractModalityTokens(
                createAIEvent({
                    $ai_usage: {
                        prompt_tokens_details: { cached_tokens_details: { audio_tokens: 50 } },
                    },
                })
            )

            expect(labelsSpy).toHaveBeenCalledTimes(1)
            expect(labelsSpy).toHaveBeenCalledWith({ status: 'extracted', source: 'openai_cache' })
        })

        it('emits source=gemini_input for Gemini promptTokensDetails extractions', () => {
            extractModalityTokens(
                createAIEvent({
                    $ai_usage: {
                        promptTokensDetails: [{ modality: 'AUDIO', tokenCount: 120 }],
                    },
                })
            )

            expect(labelsSpy).toHaveBeenCalledTimes(1)
            expect(labelsSpy).toHaveBeenCalledWith({ status: 'extracted', source: 'gemini_input' })
        })

        it('emits source=openai_input for OpenAI prompt_tokens_details.audio_tokens extractions', () => {
            extractModalityTokens(
                createAIEvent({
                    $ai_usage: {
                        prompt_tokens_details: { audio_tokens: 200 },
                    },
                })
            )

            expect(labelsSpy).toHaveBeenCalledTimes(1)
            expect(labelsSpy).toHaveBeenCalledWith({ status: 'extracted', source: 'openai_input' })
        })

        it('emits one increment per source when an event hits multiple extractors', () => {
            extractModalityTokens(
                createAIEvent({
                    $ai_usage: {
                        promptTokensDetails: [{ modality: 'AUDIO', tokenCount: 120 }],
                        candidatesTokensDetails: [{ modality: 'IMAGE', tokenCount: 1290 }],
                        cacheTokensDetails: [{ modality: 'AUDIO', tokenCount: 50 }],
                        prompt_tokens_details: {
                            audio_tokens: 200,
                            cached_tokens_details: { audio_tokens: 60 },
                        },
                    },
                })
            )

            // Five different sources fire; each gets its own increment.
            // Order is alphabetical by source for determinism.
            expect(labelsSpy).toHaveBeenCalledTimes(5)
            expect(labelsSpy).toHaveBeenNthCalledWith(1, { status: 'extracted', source: 'gemini_cache' })
            expect(labelsSpy).toHaveBeenNthCalledWith(2, { status: 'extracted', source: 'gemini_input' })
            expect(labelsSpy).toHaveBeenNthCalledWith(3, { status: 'extracted', source: 'gemini_output' })
            expect(labelsSpy).toHaveBeenNthCalledWith(4, { status: 'extracted', source: 'openai_cache' })
            expect(labelsSpy).toHaveBeenNthCalledWith(5, { status: 'extracted', source: 'openai_input' })
        })
    })
})
