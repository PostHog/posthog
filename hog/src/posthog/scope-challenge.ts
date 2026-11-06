import { parseInsufficientScopeChallenge } from '@posthog/mcp/src/lib/missing-scope'

import type { Credentials } from './credentials'

// The shape of a PostHog scope name. Scopes in a step-up can come from the server, and agents run the
// command they end up in, so nothing else may reach it.
const SCOPE_NAME = /^[a-z][a-z0-9_]*:(read|write)$/

export function isScopeName(scope: string): boolean {
    return SCOPE_NAME.test(scope)
}

export function stepUpCommand(scopes: readonly string[]): string {
    return `hog auth add ${scopes.join(' ')}`
}

// Only a login hog stored can add scopes. A personal API key, or any key from the environment,
// keeps the scopes it has.
export function canStepUp(credentials: Credentials | undefined): boolean {
    return credentials?.source === 'store' && credentials.key.status().kind === 'oauth'
}

export function addToKeyHint(scopes: readonly string[]): string {
    return `Add ${scopes.join(', ')} to the personal API key in PostHog under Settings, Personal API keys.`
}

// RFC 6750 section 3.1. PostHog sends the challenge on a 403 only to logins from apps that support
// step-up, and `scope` names every scope the request needs, held or not. A newer PostHog can name a
// scope this hog doesn't know, so the filter checks the shape, not hog's scope list.
export function challengedScopes(header: string | null): string[] | undefined {
    const scopes = parseInsufficientScopeChallenge(header)?.filter(isScopeName)
    return scopes?.length ? scopes : undefined
}
