import { PluginEvent } from '~/plugin-scaffold'

// AI gateway hosts, distinct from the older LLM gateway (gateway.{us,eu}.posthog.com).
export const AI_GATEWAY_HOSTS: ReadonlySet<string> = new Set(['ai-gateway.us.posthog.com', 'ai-gateway.eu.posthog.com'])

// `$ai_base_url` is a full URL (posthog-ai SDK) or a bare host (OTel server.address).
function extractHost(baseUrl: string): string | null {
    const candidate = baseUrl.includes('://') ? baseUrl : `https://${baseUrl}`
    try {
        return new URL(candidate).hostname.toLowerCase()
    } catch {
        return null
    }
}

/**
 * Returns the gateway host a client-side `$ai_generation` was routed through (making
 * it a duplicate of the gateway's own event), or null otherwise. The gateway's own
 * event is excluded: it sets `$ai_gateway: true` and a provider `$ai_base_url`.
 */
export function gatewayHostForClientEvent(
    event: PluginEvent,
    gatewayHosts: ReadonlySet<string> = AI_GATEWAY_HOSTS
): string | null {
    // Gateway emits only $ai_generation; leave the client's trace/span events alone.
    if (event.event !== '$ai_generation') {
        return null
    }

    const properties = event.properties
    if (!properties) {
        return null
    }

    // The gateway's own event flags itself.
    if (properties.$ai_gateway) {
        return null
    }

    const baseUrl = properties.$ai_base_url
    if (typeof baseUrl !== 'string' || baseUrl.length === 0) {
        return null
    }

    const host = extractHost(baseUrl)
    return host !== null && gatewayHosts.has(host) ? host : null
}
