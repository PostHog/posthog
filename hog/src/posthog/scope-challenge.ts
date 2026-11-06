import { parseInsufficientScopeChallenge } from '@posthog/mcp/src/lib/missing-scope'

import type { Credentials } from './credentials'

// Scopes can come from the server, and agents run the command they end up in.
const SCOPE_NAME = /^[a-z][a-z0-9_]*:(read|write)$/

export function isScopeName(scope: string): boolean {
    return SCOPE_NAME.test(scope)
}

// Asking for `x:write` grants `x:read` too, so the read scope would only lengthen the request.
export function fewestScopes(scopes: readonly string[]): string[] {
    return scopes.filter((scope) => !(scope.endsWith(':read') && scopes.includes(scope.replace(/:read$/, ':write'))))
}

// The command names the host, because `--host` or posthog.json can pick a login that isn't the
// default. Only a host made of URL characters goes in, so the command stays safe to run.
const SHELL_SAFE_HOST = /^https?:\/\/[\w.:-]+(\/[\w./-]*)?$/

export function stepUpCommand(scopes: readonly string[], host?: string): string {
    const hostFlag = host !== undefined && SHELL_SAFE_HOST.test(host) ? ` --host ${host}` : ''
    return `hog auth add${hostFlag} ${scopes.join(' ')}`
}

// A personal API key, or any key from the environment, keeps the scopes it has.
export function canStepUp(credentials: Credentials | undefined): boolean {
    return credentials?.source === 'store' && credentials.key.status().kind === 'oauth'
}

export function addToKeyHint(scopes: readonly string[]): string {
    return `Add ${scopes.join(', ')} to the personal API key in PostHog under Settings, Personal API keys.`
}

// RFC 6750 section 3.1: `scope` names every scope the request needs, held or not. A newer PostHog
// can name a scope this hog doesn't know, so the filter checks the shape only.
export function challengedScopes(header: string | null): string[] | undefined {
    const scopes = parseInsufficientScopeChallenge(header)?.filter(isScopeName)
    return scopes?.length ? scopes : undefined
}
