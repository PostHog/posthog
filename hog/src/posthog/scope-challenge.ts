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

// `--host` or posthog.json can pick a login that isn't the default. Only URL characters keep the command safe.
const SHELL_SAFE_HOST = /^https?:\/\/[\w.:-]+(\/[\w./-]*)?$/

export function hostFlag(host: string | undefined): string {
    return host !== undefined && SHELL_SAFE_HOST.test(host) ? ` --host ${host}` : ''
}

export function stepUpCommand(scopes: readonly string[], host?: string): string {
    return `hog auth add${hostFlag(host)} ${scopes.join(' ')}`
}

export function canStepUp(credentials: Credentials | undefined): boolean {
    return credentials?.source === 'store' && credentials.key.status().kind === 'oauth'
}

// A CI job's token gets its scopes from the trusted workload policy, which only an admin can change.
export function workloadScopesHint(scopes: readonly string[]): string {
    return `The trusted workload policy doesn't grant ${scopes.join(', ')}. Ask an organization admin to add them to the policy in PostHog, under the project's settings.`
}

export function addToKeyHint(scopes: readonly string[]): string {
    return `Add ${scopes.join(', ')} to the personal API key in PostHog under Settings, Personal API keys.`
}

// RFC 6750 section 3.1. A newer PostHog can name a scope this hog doesn't know, so only the shape is checked.
export function challengedScopes(header: string | null): string[] | undefined {
    const scopes = parseInsufficientScopeChallenge(header)?.filter(isScopeName)
    return scopes?.length ? scopes : undefined
}
