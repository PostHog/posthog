import { describe, expect, it } from 'vitest'

import { aiGatewaySkuFor, posthogAiGatewayModel } from './ai-gateway-model'

describe('aiGatewaySkuFor', () => {
    it.each([
        ['openai/gpt-4o', 'gpt-4o'],
        ['anthropic/claude-sonnet-4-6', 'claude-sonnet-4-6'],
        ['gpt-4o', 'gpt-4o'],
    ])('maps %s -> %s', (specModel, sku) => {
        expect(aiGatewaySkuFor(specModel)).toBe(sku)
    })
})

describe('posthogAiGatewayModel', () => {
    // The gateway reads only `Authorization: Bearer`. pi-ai's anthropic-messages
    // shape would otherwise send the key as `x-api-key` and 401 at the gateway —
    // so the Bearer header must be pinned regardless of provider shape.
    it.each(['anthropic/claude-sonnet-4-6', 'openai/gpt-4o'])('pins Authorization: Bearer for %s', (specModel) => {
        const model = posthogAiGatewayModel({
            specModel,
            baseUrl: 'https://ai-gateway.example.com/v1',
            apiKey: 'phs_test-key',
        })
        expect(model.headers?.Authorization).toBe('Bearer phs_test-key')
        expect(model.provider).toBe('posthog-ai-gateway')
    })

    // anthropic-messages: the SDK appends `/v1/messages`, so the trailing `/v1`
    // is stripped. openai shapes append their own suffix, so `/v1` is kept.
    it.each([
        ['anthropic/claude-sonnet-4-6', 'https://ai-gateway.example.com'],
        ['openai/gpt-4o', 'https://ai-gateway.example.com/v1'],
    ])('resolves baseUrl for %s', (specModel, expectedBaseUrl) => {
        const model = posthogAiGatewayModel({
            specModel,
            baseUrl: 'https://ai-gateway.example.com/v1',
            apiKey: 'phs_test-key',
        })
        expect(model.baseUrl).toBe(expectedBaseUrl)
    })
})
