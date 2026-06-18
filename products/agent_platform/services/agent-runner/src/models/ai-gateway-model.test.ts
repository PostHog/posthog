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

    it('strips /v1 for the anthropic-messages shape and keeps it for openai', () => {
        const anthropic = posthogAiGatewayModel({
            specModel: 'anthropic/claude-sonnet-4-6',
            baseUrl: 'https://ai-gateway.example.com/v1',
            apiKey: 'phs_test-key',
        })
        const openai = posthogAiGatewayModel({
            specModel: 'openai/gpt-4o',
            baseUrl: 'https://ai-gateway.example.com/v1',
            apiKey: 'phs_test-key',
        })
        expect(anthropic.baseUrl).toBe('https://ai-gateway.example.com')
        expect(openai.baseUrl).toBe('https://ai-gateway.example.com/v1')
    })
})
