import { HogError } from '@/core/errors'

// A scope as PostHog names one. A challenge comes from the server, and hog puts its scopes into a
// command for a person or an agent to run, so anything else is dropped.
const SCOPE = /^[a-z][a-z0-9_]*:(read|write)$/

export function stepUpCommand(scopes: readonly string[]): string {
    return `hog auth add ${scopes.join(' ')}`
}

// RFC 6750 section 3: `WWW-Authenticate: Bearer error="insufficient_scope", scope="a b"`. PostHog
// sends it on a 403 only to logins from apps that support step-up, and `scope` names every scope
// the request needs, held or not.
export function challengedScopes(header: string | null): string[] | undefined {
    const params = /^\s*Bearer\s+(.*)$/i.exec(header ?? '')?.[1]
    if (params === undefined) {
        return undefined
    }
    const values = new Map<string, string>()
    for (const [, name = '', quoted, token] of params.matchAll(
        /([A-Za-z_]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))/g
    )) {
        values.set(name.toLowerCase(), (quoted ?? token ?? '').replace(/\\(.)/g, '$1'))
    }
    if (values.get('error') !== 'insufficient_scope') {
        return undefined
    }
    const scopes = (values.get('scope') ?? '').split(/\s+/).filter((scope) => SCOPE.test(scope))
    return scopes.length > 0 ? scopes : undefined
}

// Agents get the scopes and the command as data next to the error code, and run the command
// themselves: hog never waits for a person on their behalf.
export function stepUpRequired(scopes: readonly string[]): HogError {
    const command = stepUpCommand(scopes)
    const them = scopes.length === 1 ? 'it' : 'them'
    return new HogError(
        'step_up_required',
        `Your login needs ${scopes.join(', ')} for this.`,
        `Run \`${command}\` to add ${them} to your login, then run the command again.`,
        undefined,
        { scopes: [...scopes], command }
    )
}
