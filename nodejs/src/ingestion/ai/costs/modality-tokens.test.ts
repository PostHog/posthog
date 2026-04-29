import { EventWithProperties, extractModalityTokens } from './modality-tokens'

function createAIEvent(properties?: Record<string, any>): EventWithProperties {
    return {
        event: '$ai_generation',
        properties: properties || {},
        ip: '',
        site_url: '',
        team_id: 0,
        now: '',
        distinct_id: '',
        uuid: '',
        timestamp: '',
    }
}

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
})
