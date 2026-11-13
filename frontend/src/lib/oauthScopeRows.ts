import {
    API_SCOPES,
    clampScopeLevel,
    getScopeDescription,
    getScopeGroupLabel,
    groupScopeRows,
    scopeRowWarning,
    type ScopeAccessLevel,
    type ScopePickerGroup,
    type ScopePickerRow,
} from 'lib/scopes'

export const IDENTITY_SCOPES = ['openid', 'profile', 'email', 'introspection']

const scopeObjectKey = (scope: string): string => (scope === '*' ? '*' : scope.split(':')[0])

export type OAuthScopeRow = ScopePickerRow & {
    /** Required floor — the grant can never go below this. 'none' when not required. */
    minLevel: ScopeAccessLevel
    /** Requested ceiling — the grant can never go above what the client asked for. */
    maxLevel: Exclude<ScopeAccessLevel, 'none'>
    /** True when the floor comes from an earlier grant to this app rather than the app's required scopes. */
    alreadyGranted: boolean
}

export type OAuthScopeGroup = ScopePickerGroup<OAuthScopeRow>

// The floor and the ceiling as the reasons a level is not available, in the words the row shows.
// The shared clamp and group control work from these, so a group set to write holds a read-only
// row at read and a group set to none holds a required row at read.
const oauthDisabledReasons = (
    minLevel: ScopeAccessLevel,
    maxLevel: ScopeAccessLevel,
    appName: string,
    alreadyGranted: boolean
): Partial<Record<ScopeAccessLevel, string>> => ({
    ...(minLevel !== 'none'
        ? {
              none: alreadyGranted
                  ? `Already granted to ${appName}`
                  : `${appName} requires at least ${minLevel} access`,
          }
        : {}),
    ...(minLevel === 'write'
        ? {
              read: alreadyGranted
                  ? `Write access is already granted to ${appName}`
                  : `${appName} requires write access`,
          }
        : {}),
    ...(maxLevel !== 'write' ? { write: `Not requested by ${appName}` } : {}),
})

const WILDCARD_LABEL = 'All PostHog data'
const WILDCARD_GROUP_LABEL = 'Full access'

// Past this many rows every group starts closed, so each header reads as a summary.
export const SCOPE_GROUPS_OPEN_MAX_ROWS = 8

// Fallback for scopes absent from API_SCOPES (e.g. server-side scopes the local list lags
// behind) — derive a readable label from the raw key.
const humanizeScopeKey = (key: string): string => {
    const humanized = key.replace(/_/g, ' ')
    return humanized.charAt(0).toUpperCase() + humanized.slice(1)
}

// Required scopes are tracked per object at the action level that's required, so a
// required `obj:read` still lets the read-only toggle downgrade an optional `obj:write`.
export type RequiredLevel = 'read' | 'write'

export const requiredLevelsFromScopes = (requiredScopes: string[]): Map<string, RequiredLevel> => {
    const levels = new Map<string, RequiredLevel>()
    for (const scope of requiredScopes) {
        if (!scope.includes(':') && scope !== '*') {
            continue
        }
        const key = scopeObjectKey(scope)
        const level: RequiredLevel = scope === '*' || scope.endsWith(':write') ? 'write' : 'read'
        if (level === 'write' || !levels.has(key)) {
            levels.set(key, level)
        }
    }
    return levels
}

export type ScopeAccessSelections = Record<string, ScopeAccessLevel>

// One row per scope object. The requested set caps the ceiling, the required set
// sets the floor, and the user's selection is clamped between the two, so no pick
// (including a group or list-wide pick) can grant more than requested or less than required.
export function buildOAuthScopeRows(
    consentResourceScopes: string[],
    scopeAccessSelections: ScopeAccessSelections,
    requiredScopeLevels: Map<string, RequiredLevel>,
    alreadyGrantedScopeLevels: Map<string, RequiredLevel>,
    appName: string
): OAuthScopeRow[] {
    const rows = consentResourceScopes.map((scope): OAuthScopeRow => {
        const key = scopeObjectKey(scope)
        const maxLevel: 'read' | 'write' = scope === '*' || scope.endsWith(':write') ? 'write' : 'read'
        const requiredLevel = requiredScopeLevels.get(key)
        const grantedLevel = alreadyGrantedScopeLevels.get(key)
        const alreadyGranted = grantedLevel !== undefined && (grantedLevel === 'write' || requiredLevel !== 'write')
        const minLevel: ScopeAccessLevel = (alreadyGranted ? grantedLevel : requiredLevel) ?? 'none'
        const disabledReasons = oauthDisabledReasons(minLevel, maxLevel, appName, alreadyGranted)
        const selected = scopeAccessSelections[key] ?? maxLevel
        const value = clampScopeLevel({ key, label: key, value: selected, disabledReasons }, selected)
        const apiScope = key === '*' ? undefined : API_SCOPES.find((s) => s.key === key)
        return {
            key,
            label: key === '*' ? WILDCARD_LABEL : (apiScope?.objectName ?? humanizeScopeKey(key)),
            info: apiScope?.info,
            warning: key === '*' ? undefined : scopeRowWarning(apiScope, key, value),
            muted: value === 'none',
            disabledReasons,
            minLevel,
            maxLevel,
            value,
            alreadyGranted,
        }
    })
    return rows.sort((a, b) => a.label.localeCompare(b.label))
}

// The resource scopes the rows grant. `wildcardRead` gives the read-only form of `*`.
export function grantedResourceScopes(
    scopeRows: OAuthScopeRow[],
    requestedScopes: string[],
    wildcardRead: () => string[]
): string[] {
    return scopeRows.flatMap((row) => {
        if (row.value === 'none') {
            return []
        }
        if (row.key === '*') {
            return row.value === 'write' ? ['*'] : wildcardRead()
        }
        // Write grants read too, but clients diff the granted `scope` against what they
        // asked for, so a missing `:read` reads as a partial grant. Spell both out when
        // the client asked for both, and only then: granting a half it never requested
        // is the same mismatch in the other direction.
        if (row.value === 'write') {
            const readScope = `${row.key}:read`
            return requestedScopes.includes(readScope) ? [readScope, `${row.key}:write`] : [`${row.key}:write`]
        }
        return [`${row.key}:${row.value}`]
    })
}

const IDENTITY_SCOPE_LABELS: Record<string, string> = {
    openid: 'User ID',
    email: 'Email address',
    profile: 'Profile',
}

// Display-only: the grant takes identity scopes from the request, never from these rows.
export function identityScopeRows(scopes: string[], appName: string): OAuthScopeRow[] {
    return scopes
        .filter((scope) => IDENTITY_SCOPE_LABELS[scope])
        .map((scope) => ({
            key: scope,
            label: IDENTITY_SCOPE_LABELS[scope],
            info: getScopeDescription(scope),
            value: 'read',
            muted: false,
            disabledReasons: { none: `${appName} needs this to identify you`, write: 'Account details are read-only' },
            minLevel: 'read',
            maxLevel: 'read',
            alreadyGranted: false,
        }))
}

export function oauthScopeGroups(resourceRows: OAuthScopeRow[], identityRows: OAuthScopeRow[]): OAuthScopeGroup[] {
    const wildcardRows = resourceRows.filter((row) => row.key === '*')
    const identityKeys = new Set(identityRows.map((row) => row.key))
    return [
        ...(wildcardRows.length > 0 ? [{ label: WILDCARD_GROUP_LABEL, rows: wildcardRows }] : []),
        ...groupScopeRows([...identityRows, ...resourceRows.filter((row) => row.key !== '*')], (row) =>
            getScopeGroupLabel(identityKeys.has(row.key) ? 'user' : row.key)
        ),
    ]
}

export function scopeGroupsStartOpen(groups: OAuthScopeGroup[]): boolean {
    return groups.reduce((count, group) => count + group.rows.length, 0) <= SCOPE_GROUPS_OPEN_MAX_ROWS
}
