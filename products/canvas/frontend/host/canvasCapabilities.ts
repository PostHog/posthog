import type { CanvasCapabilitiesApi } from '../generated/api.schemas'

/**
 * Throws unless the rendered build or source project's manifest admits this request.
 */
export function assertCanvasCapability(
    capabilities: CanvasCapabilitiesApi | null | undefined,
    method: string,
    payload: unknown
): void {
    if (!capabilities) {
        throw new Error('Canvas capability manifest is unavailable')
    }
    const input = (payload ?? {}) as Record<string, unknown>

    switch (method) {
        case 'query':
            if (!capabilities.posthog.inlineQueries) {
                throw new Error('Inline queries are not allowed by this canvas')
            }
            return
        case 'loadInsight':
            if (typeof input.shortId !== 'string' || !capabilities.posthog.insights.includes(input.shortId)) {
                throw new Error('Insight is not allowed by this canvas')
            }
            return
        case 'capture':
            if (typeof input.event !== 'string' || !capabilities.posthog.captureEvents.includes(input.event)) {
                throw new Error('Event capture is not allowed by this canvas')
            }
            return
        case 'stateGet':
        case 'stateSet':
        case 'stateList': {
            const scope = (input.scope ?? (method === 'stateList' ? undefined : 'user')) as
                | 'user'
                | 'shared'
                | undefined
            const declared = capabilities.posthog.state ?? []
            // The backend uses the current head's scopes, which can exceed this build's scopes.
            if (
                scope
                    ? !declared.includes(scope)
                    : !['user', 'shared'].every((value) => declared.includes(value as 'user' | 'shared'))
            ) {
                throw new Error(`State scope "${scope ?? 'any'}" is not allowed by this canvas`)
            }
            return
        }
        case 'actionInvoke': {
            const verb = input.verb
            if (typeof verb !== 'string' || !(capabilities.posthog.actions ?? []).includes(verb)) {
                throw new Error(`Action "${typeof verb === 'string' ? verb : ''}" is not allowed by this canvas`)
            }
            return
        }
        case 'agentRequest':
            if (!capabilities.posthog.agentRequests) {
                throw new Error('Agent requests are not allowed by this canvas')
            }
            return
        case 'connectorCall': {
            const provider = typeof input.provider === 'string' ? input.provider : ''
            const tool = typeof input.tool === 'string' ? input.tool : ''
            const declared = (capabilities.connectors ?? []).find((entry) => entry.provider === provider)
            if (!provider || !tool || !declared?.tools.includes(tool)) {
                throw new Error(`Connector tool "${provider}/${tool}" is not allowed by this canvas`)
            }
            return
        }
        default:
            throw new Error(`Method "${method}" is not allowed by this canvas`)
    }
}
