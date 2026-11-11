import { getLlmGatewayUrl, resolveLlmGatewayUrl } from '@posthog/agent/posthog-api'

export function legacyCallers(apiHost: string, posthogAPI: { getLlmGatewayUrl(): string }): string[] {
    return [
        // ruleid: no-new-legacy-llm-gateway-callers-typescript
        getLlmGatewayUrl(apiHost),
        // ruleid: no-new-legacy-llm-gateway-callers-typescript
        posthogAPI.getLlmGatewayUrl(),
        // ruleid: no-new-legacy-llm-gateway-callers-typescript
        resolveLlmGatewayUrl(process.env.AI_GATEWAY_URL, apiHost),
        // ruleid: no-new-legacy-llm-gateway-callers-typescript
        process.env.LLM_GATEWAY_URL ?? '',
        // ruleid: no-new-legacy-llm-gateway-callers-typescript
        'https://gateway.eu.posthog.com/posthog_code',
    ]
}

export function goCallers(apiHost: string): string[] {
    return [
        // ok: no-new-legacy-llm-gateway-callers-typescript
        resolveLlmGatewayUrl(process.env.AI_GATEWAY_URL, apiHost, 'posthog_code', { slugless: true }),
        // ok: no-new-legacy-llm-gateway-callers-typescript
        'https://ai-gateway.eu.posthog.com/v1',
    ]
}
