import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { AI_GATEWAY_HOSTS, gatewayHostForClientEvent } from './gateway-dedup'

const createEvent = (event: string, properties: Record<string, unknown>) => createTestPluginEvent({ event, properties })

describe('gatewayHostForClientEvent', () => {
    it('exposes both regional AI gateway hosts', () => {
        expect([...AI_GATEWAY_HOSTS].sort()).toEqual(['ai-gateway.eu.posthog.com', 'ai-gateway.us.posthog.com'])
    })

    it('does not target the older LLM gateway hosts', () => {
        expect(AI_GATEWAY_HOSTS.has('gateway.us.posthog.com')).toBe(false)
        expect(AI_GATEWAY_HOSTS.has('gateway.eu.posthog.com')).toBe(false)
    })

    it.each([
        ['SDK full URL, US gateway', 'https://ai-gateway.us.posthog.com/v1', 'ai-gateway.us.posthog.com'],
        ['SDK full URL, EU gateway', 'https://ai-gateway.eu.posthog.com/v1', 'ai-gateway.eu.posthog.com'],
        ['bare host from OTel server.address', 'ai-gateway.us.posthog.com', 'ai-gateway.us.posthog.com'],
        ['host with port', 'https://ai-gateway.us.posthog.com:443/v1', 'ai-gateway.us.posthog.com'],
        ['uppercased host', 'https://AI-GATEWAY.US.POSTHOG.COM/v1', 'ai-gateway.us.posthog.com'],
    ])('matches a gateway-routed $ai_generation (%s)', (_label, baseUrl, expectedHost) => {
        const event = createEvent('$ai_generation', { $ai_base_url: baseUrl })
        expect(gatewayHostForClientEvent(event)).toBe(expectedHost)
    })

    it.each([
        [
            'gateway flag is true (the canonical event)',
            '$ai_generation',
            { $ai_base_url: 'https://ai-gateway.us.posthog.com', $ai_gateway: true },
        ],
        ['provider host (direct call)', '$ai_generation', { $ai_base_url: 'https://api.anthropic.com' }],
        ['older LLM gateway host', '$ai_generation', { $ai_base_url: 'https://gateway.us.posthog.com/v1' }],
        ['non-generation event with gateway host', '$ai_span', { $ai_base_url: 'https://ai-gateway.us.posthog.com' }],
        ['no base_url', '$ai_generation', {}],
        ['empty base_url', '$ai_generation', { $ai_base_url: '' }],
        ['non-string base_url', '$ai_generation', { $ai_base_url: 123 }],
        ['unparseable base_url', '$ai_generation', { $ai_base_url: 'http://' }],
        ['lookalike subdomain', '$ai_generation', { $ai_base_url: 'https://ai-gateway.us.posthog.com.evil.com' }],
    ])('does not match (%s)', (_label, eventName, properties) => {
        const event = createEvent(eventName, properties)
        expect(gatewayHostForClientEvent(event)).toBeNull()
    })

    it('treats a truthy non-boolean $ai_gateway as the canonical event', () => {
        const event = createEvent('$ai_generation', {
            $ai_base_url: 'https://ai-gateway.us.posthog.com',
            $ai_gateway: 'true',
        })
        expect(gatewayHostForClientEvent(event)).toBeNull()
    })

    it('honours a custom host set', () => {
        const event = createEvent('$ai_generation', { $ai_base_url: 'https://my-proxy.example.com/v1' })
        expect(gatewayHostForClientEvent(event, new Set(['my-proxy.example.com']))).toBe('my-proxy.example.com')
    })
})
