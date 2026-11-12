import { z } from 'zod'

import { LEGACY_SCOPE_FALLBACKS, OAUTH_SCOPES_SUPPORTED } from '@posthog/mcp/src/lib/oauth-scopes.generated'

import { HogError } from '@/core/errors'

// Identity scopes such as `openid` come with every login, so `hog auth add` takes only these.
const RESOURCE_SCOPES = OAUTH_SCOPES_SUPPORTED.filter((scope) => scope.includes(':'))

const ScopeSchema = z.enum(RESOURCE_SCOPES).brand<'Scope'>()

export type Scope = z.output<typeof ScopeSchema>

export function parseScope(raw: string): Scope {
    const parsed = ScopeSchema.safeParse(raw)
    if (parsed.success) {
        return parsed.data
    }
    if (ScopeSchema.safeParse(`${raw}:read`).success) {
        throw new HogError(
            'unknown_scope',
            `"${raw}" has no access level.`,
            `Add one, as in \`hog auth add ${raw}:write\`.`
        )
    }
    // A newer PostHog can ask for a scope this hog build doesn't list yet.
    const hint = /^[a-z][a-z0-9_]*:(read|write)$/.test(raw)
        ? 'Check the name. If PostHog asked for it, update hog to a version that knows it.'
        : 'A scope is an object and an access level, such as insight:read or insight:write.'
    throw new HogError('unknown_scope', `hog doesn't know the scope "${raw}".`, hint)
}

// Checked like `hasScope` in services/mcp/src/lib/api.ts (`*`, write grants read, legacy scopes),
// which hog can't import because it uses the MCP server's own `@/` path.
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
