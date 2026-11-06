import { z } from 'zod'

import { LEGACY_SCOPE_FALLBACKS, OAUTH_SCOPES_SUPPORTED } from '@posthog/mcp/src/lib/oauth-scopes.generated'

import { HogError } from '@/core/errors'

// The scopes `hog auth add` takes: every scope PostHog lets a login ask for that grants access to
// data. Identity scopes such as `openid` come with every login.
const RESOURCE_SCOPES = OAUTH_SCOPES_SUPPORTED.filter((scope) => scope.includes(':'))

const ScopeSchema = z.enum(RESOURCE_SCOPES).brand<'Scope'>()

export type Scope = z.output<typeof ScopeSchema>

export function parseScope(raw: string): Scope {
    const parsed = ScopeSchema.safeParse(raw)
    if (parsed.success) {
        return parsed.data
    }
    throw new HogError(
        'unknown_scope',
        `PostHog has no scope named "${raw}".`,
        raw.includes(':')
            ? 'A scope is an object and an access level, such as insight:read or insight:write.'
            : `Add the access level, as in \`hog auth add ${raw}:write\`.`
    )
}

// The scopes in `wanted` that `held` doesn't grant, checked the way PostHog checks them: `*` grants
// everything, `x:write` grants `x:read`, and a legacy scope grants the scope that was split off it.
// `hasScope` in services/mcp/src/lib/api.ts holds the same rules. hog can't import it, because that
// module imports through the MCP server's own `@/` path.
export function scopesNotCovered(held: readonly string[], wanted: readonly string[]): string[] {
    if (held.includes('*')) {
        return []
    }
    const granted = new Set(held)
    const grants = (scope: string): boolean => {
        const [object = '', action = ''] = scope.split(':')
        const legacy = LEGACY_SCOPE_FALLBACKS.get(object)
        const objects = legacy ? [object, legacy] : [object]
        const actions = action === 'read' ? ['read', 'write'] : [action]
        return objects.some((o) => actions.some((a) => granted.has(`${o}:${a}`)))
    }
    return [...new Set(wanted)].filter((scope) => !grants(scope))
}
