import { parseInsufficientScopeChallenge } from '@posthog/mcp/src/lib/missing-scope'

import { HogError } from '@/core/errors'

import type { Credentials } from './credentials'

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
// step-up, and `scope` names every scope the request needs, held or not. hog puts these scopes into
// a command a person or an agent runs, so `isScope` keeps only names PostHog has.
export function challengedScopes(header: string | null, isScope: (scope: string) => boolean): string[] | undefined {
    const scopes = parseInsufficientScopeChallenge(header)?.filter(isScope)
    return scopes?.length ? scopes : undefined
}

export function stepUpRequired(
    scopes: readonly string[],
    message = `Your login needs ${scopes.join(', ')} for this.`
): HogError {
    const command = stepUpCommand(scopes)
    return new HogError(
        'step_up_required',
        message,
        `Run \`${command}\` to add the scopes to your login, then run the command again.`,
        undefined,
        { scopes: [...scopes], command }
    )
}
