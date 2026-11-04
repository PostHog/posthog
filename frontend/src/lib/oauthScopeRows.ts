import {
    API_SCOPES,
    clampScopeLevel,
    getScopeDescription,
    groupScopeRows,
    type ScopeAccessLevel,
    type ScopePickerGroup,
    type ScopePickerRow,
} from 'lib/scopes'

export const IDENTITY_SCOPES = ['openid', 'profile', 'email', 'introspection']

const scopeObjectKey = (scope: string): string => (scope === '*' ? '*' : scope.split(':')[0])

export type OAuthScopeRow = ScopePickerRow & {
    /** Full sentence description at the granted level, for the locked (checkmark) list. */
    description: string
    /** Required floor — the grant can never go below this. 'none' when not required. */
    minLevel: ScopeAccessLevel
    /** Requested ceiling — the grant can never go above what the client asked for. */
    maxLevel: Exclude<ScopeAccessLevel, 'none'>
    /** True when minLevel === maxLevel: nothing to choose, rendered as a locked checkmark row. */
    locked: boolean
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

// A request with this many adjustable rows or fewer shows a flat alphabetical list. Group
// headers only help when the list is long.
export const SCOPE_GROUPING_MIN_ROWS = 10

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

export type ScopeAccessSelections = { bulk: ScopeAccessLevel | null; overrides: Record<string, ScopeAccessLevel> }

// One row per scope object. The requested set caps the ceiling, the required set
// sets the floor, and the user's selection is clamped between the two, so no pick
// (including bulk actions) can grant more than requested or less than required.
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
        const selected = scopeAccessSelections.overrides[key] ?? scopeAccessSelections.bulk ?? maxLevel
        const value = clampScopeLevel({ key, label: key, value: selected, disabledReasons }, selected)
        const apiScope = key === '*' ? undefined : API_SCOPES.find((s) => s.key === key)
        const grantedScope = scope === '*' && value === 'write' ? '*' : `${key}:${value}`
        return {
            key,
            label: key === '*' ? WILDCARD_LABEL : (apiScope?.objectName ?? humanizeScopeKey(key)),
            description: getScopeDescription(grantedScope) ?? grantedScope,
            info: apiScope?.info,
            warning: value === 'none' ? undefined : apiScope?.warnings?.[value],
            muted: value === 'none',
            disabledReasons,
            minLevel,
            maxLevel,
            value,
            locked: minLevel === maxLevel,
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

// What the consent list shows for the identity scopes a client asked for, such as `openid`.
export function identityScopeDescriptions(scopes: string[]): string[] {
    return scopes
        .filter((scope) => IDENTITY_SCOPES.includes(scope))
        .map(getScopeDescription)
        .filter((description): description is string => !!description)
}

// The adjustable rows in groups, or null when the list is short enough to show flat.
export function scopeGroupsToShow(adjustableScopeRows: OAuthScopeRow[]): OAuthScopeGroup[] | null {
    return adjustableScopeRows.length > SCOPE_GROUPING_MIN_ROWS ? groupScopeRows(adjustableScopeRows) : null
}
