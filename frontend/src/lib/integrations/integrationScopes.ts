import { IntegrationKind, IntegrationType, SLACK_INTEGRATION_SCOPES } from '~/types'

import { getIntegrationNameFromKind } from './utils'

/**
 * Extract the granted OAuth scopes from an integration's stored config. Tolerates the
 * various shapes different providers persist: ``config.scope`` vs ``config.scopes``,
 * space- or comma-separated strings, or a pre-split array. Returns an empty array when
 * no recognizable scope list is present (e.g. legacy rows predating the field).
 *
 * Exported so any caller that needs to decide "is this install missing a scope" (the
 * banner below, the OAuth landing-page status hook, etc.) reaches the same verdict.
 */
export function getGrantedScopes(integration: IntegrationType): string[] {
    const candidates: string[][] = []

    for (const raw of [integration.config?.scope, integration.config?.scopes]) {
        if (typeof raw === 'string') {
            // Pick the delimiter explicitly. Pushing both comma- and space-split results and
            // letting "longest array wins" decide was a heuristic that silently mangled mixed
            // delimiters like ``"read write,admin"`` into one of several wrong shapes.
            const split = raw.includes(',') ? raw.split(',') : raw.split(' ')
            candidates.push(split.map((scope) => scope.trim()).filter(Boolean))
        } else if (Array.isArray(raw)) {
            candidates.push(raw)
        }
    }

    return candidates.reduce((a, b) => (a.length > b.length ? a : b), [] as string[])
}

/** Scopes from ``schema.requiredScopes`` that the integration hasn't granted. */
export function getMissingScopes(integration: IntegrationType, requiredScopes: string[]): string[] {
    const granted = getGrantedScopes(integration)
    if (granted.length === 0) {
        return []
    }
    return requiredScopes.filter((scope) => !granted.includes(scope))
}

/** Scopes PostHog asks for on the authorize URL, for the kinds where the frontend knows the full list. */
export function requestedScopesForKind(kind: IntegrationKind): string[] {
    return kind === 'slack' ? [...SLACK_INTEGRATION_SCOPES] : []
}

export function describeScopeShortfall(kind: IntegrationKind, missingScopes: string[]): string {
    const name = getIntegrationNameFromKind(kind)
    const permissions = missingScopes.length === 1 ? 'permission' : 'permissions'
    return (
        `${name} is connected, but it did not grant ${missingScopes.length} ${permissions}: ${missingScopes.join(', ')}. ` +
        `Reconnecting again will not fix this. Ask a ${name} workspace admin to approve or reinstall the PostHog app, then reconnect.`
    )
}
