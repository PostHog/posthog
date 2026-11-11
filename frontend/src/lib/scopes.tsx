import { AGENT_USE_CASE_SCOPES } from 'lib/agentScopes.generated'
import { RISKY_SCOPE_WARNINGS } from 'lib/oauthScopes.generated'
import { SCOPE_DOCS, SCOPE_GROUPS } from 'lib/scopeDocs.generated'

import type { APIScopeAction, APIScopeObject } from '~/types'

// Fallback when the user has not loaded yet. The real limit comes from the `personal_api_keys`
// entitlement and travels on the user as `personal_api_keys_limit`.
export const DEFAULT_MAX_API_KEYS_PER_USER = 10

export type ScopeAccessLevel = 'none' | 'read' | 'write'

const SCOPE_ACCESS_LEVELS: readonly ScopeAccessLevel[] = ['none', 'read', 'write']

const SCOPE_ACCESS_LEVEL_LABELS: Record<ScopeAccessLevel, string> = { none: 'no access', read: 'read', write: 'write' }

/**
 * One scope object in a picker, with the levels it can take. The OAuth consent screen and the key
 * modal both build this shape, so one group control serves both. A level with no disabled reason is
 * available. The reason is the text the row's segment shows.
 */
export type ScopePickerRow = {
    key: string
    label: string
    value: ScopeAccessLevel
    disabledReasons: Partial<Record<ScopeAccessLevel, string>>
    info?: string | JSX.Element
    warning?: string | JSX.Element
    /** True when the row is dimmed, for example at no access or when a project scoped key rules it out. */
    muted?: boolean
}

export type ScopePickerGroup<Row extends ScopePickerRow = ScopePickerRow> = {
    label: string
    rows: Row[]
}

export const scopeRowAllows = (row: ScopePickerRow, level: ScopeAccessLevel): boolean => !row.disabledReasons[level]

// The nearest available level: the same or a lower one first, so a group set to write holds a
// read-only row at read, then a higher one, so a row an app requires at read never drops to none.
export const clampScopeLevel = (row: ScopePickerRow, level: ScopeAccessLevel): ScopeAccessLevel => {
    const index = SCOPE_ACCESS_LEVELS.indexOf(level)
    const candidates = [...SCOPE_ACCESS_LEVELS.slice(0, index + 1).reverse(), ...SCOPE_ACCESS_LEVELS.slice(index + 1)]
    return candidates.find((candidate) => scopeRowAllows(row, candidate)) ?? row.value
}

// The group shows a level as selected when each row is at that level after the clamp. A level no
// row can take is never selected, which removes the tie between write and read in a group with no
// writable row, and between none and read in a group of required rows.
export const scopeGroupLevel = (rows: ScopePickerRow[]): ScopeAccessLevel | undefined =>
    [...SCOPE_ACCESS_LEVELS]
        .reverse()
        .find(
            (level) =>
                rows.some((row) => scopeRowAllows(row, level)) &&
                rows.every((row) => row.value === clampScopeLevel(row, level))
        )

// A level is disabled on the group when no row can take it. The reason is the rows' own.
export const scopeGroupDisabledReasons = (rows: ScopePickerRow[]): Partial<Record<ScopeAccessLevel, string>> =>
    Object.fromEntries(
        SCOPE_ACCESS_LEVELS.flatMap((level) => {
            const reason = rows.find((row) => !scopeRowAllows(row, level))?.disabledReasons[level]
            return reason && rows.every((row) => !scopeRowAllows(row, level)) ? [[level, reason]] : []
        })
    )

// Tooltip on the selected group level, for the rows that sit at another level after the clamp.
// Each row gives the reason its own segment shows, so the text names the real cause.
export const scopeGroupTooltip = (rows: ScopePickerRow[], level: ScopeAccessLevel | undefined): string | undefined => {
    if (!level) {
        return undefined
    }
    const counts = new Map<string, number>()
    for (const row of rows.filter((row) => row.value !== level)) {
        const note = `at ${SCOPE_ACCESS_LEVEL_LABELS[row.value]}: ${row.disabledReasons[level] ?? ''}`
        counts.set(note, (counts.get(note) ?? 0) + 1)
    }
    const notes = [...counts].map(
        ([note, count]) => `${count} of these permissions ${count === 1 ? 'stays' : 'stay'} ${note}.`
    )
    return notes.length > 0 ? notes.join(' ') : undefined
}

export const countScopeRowsByLevel = (rows: { value: ScopeAccessLevel }[]): Record<ScopeAccessLevel, number> => {
    const counts: Record<ScopeAccessLevel, number> = { none: 0, read: 0, write: 0 }
    for (const row of rows) {
        counts[row.value] += 1
    }
    return counts
}

export type APIScope = {
    key: APIScopeObject
    objectName: string
    objectPlural: string
    info?: string | JSX.Element
    disabledActions?: ('read' | 'write')[]
    disabledWhenProjectScoped?: boolean
    warnings?: Partial<Record<'read' | 'write', string | JSX.Element>>
    /** Mirrors `PRIVILEGED_SCOPES` in posthog/scopes.py — excluded from every unprivileged preset. */
    unprivilegedExcluded?: boolean
}

/** Fields a scope search matches against. `label` covers rows that show a name outside `objectName`. */
export type ScopeSearchFields = {
    key?: string
    objectName?: string
    objectPlural?: string
    label?: string
    info?: string | JSX.Element
}

/**
 * Shared scope-search matcher for every scope picker. It splits the term into tokens and requires
 * each token to appear in the scope's key, names, or info text, so a multi-word or plural search
 * still matches the label the row shows. Keep all pickers on this one matcher so they can't drift.
 */
export function scopeMatchesSearch(scope: ScopeSearchFields, searchTerm: string): boolean {
    const tokens = searchTerm.toLowerCase().trim().split(/\s+/).filter(Boolean)
    if (tokens.length === 0) {
        return true
    }
    const haystack = [scope.key, scope.objectName, scope.objectPlural, scope.label, scope.info]
        .filter((field): field is string => typeof field === 'string')
        .join(' ')
        .toLowerCase()
    return tokens.every((token) => haystack.includes(token))
}

/**
 * The warning a scope picker row shows for a risky scope at the picked level. The backend owns the list of
 * risky scopes and their wording. Write access includes read, so a write pick also shows the read warning.
 */
export const riskyScopeWarning = (
    scopeObject: string,
    level: ScopeAccessLevel,
    riskyScopes: Record<string, string>
): string | undefined => {
    const actions: APIScopeAction[] = level === 'write' ? ['write', 'read'] : level === 'read' ? ['read'] : []
    const warnings = actions.map((action) => riskyScopes[`${scopeObject}:${action}`]).filter(Boolean)
    return warnings.length > 0 ? `Add with care: ${warnings.join(' ')}` : undefined
}

/**
 * What a personal API key or OAuth scope row warns about at the picked level: the scope's own note, such as a
 * feature flag it also writes, followed by the backend's risky scope warning.
 */
export function scopeRowWarning(
    apiScope: APIScope | undefined,
    scopeObject: string,
    level: ScopeAccessLevel
): string | JSX.Element | undefined {
    const note = level === 'none' ? undefined : apiScope?.warnings?.[level]
    const risky = riskyScopeWarning(scopeObject, level, RISKY_SCOPE_WARNINGS)
    return note && risky ? (
        <>
            {note} {risky}
        </>
    ) : (
        (note ?? risky)
    )
}

// Every scope object a picker offers, built from the backend ScopeDoc declarations.
export const API_SCOPES: APIScope[] = Object.entries(SCOPE_DOCS).map(([key, doc]) => ({
    key: key as APIScopeObject,
    objectName: doc.name,
    objectPlural: doc.plural,
    info: doc.description,
    disabledActions: (['read', 'write'] as const).filter((action) => !doc.actions.includes(action)),
    disabledWhenProjectScoped: doc.organizationWide,
    unprivilegedExcluded: doc.privileged,
    warnings: doc.writeRequires ? { write: doc.writeRequires.reason } : undefined,
}))
API_SCOPES.sort((a, b) => a.objectName.localeCompare(b.objectName))

// Keep in sync with PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION in posthog/scopes.py.
// posthog/test/test_scopes.py compares the two lists.
export const PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION = [
    'endpoint:read',
    'feature_flag:read',
    'account:read',
    'account:write',
    'support_ticket:read',
    'loop:write',
    'experiment:read',
    'offline_evaluation_ingestion:write',
    'billing:read',
    'replay_scanner:write',
    'session_recording:read',
    'hog_flow:read',
    'hog_flow:write',
    'messaging_preference:write',
    'transactional_email:read',
    'transactional_email:write',
    'llm_prompt:read',
] as const

export type ProjectSecretAPIKeyAllowedScope = (typeof PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION)[number]

const API_KEY_CREATION_ACTIONS = ['read', 'write'] as const

// Scopes the manual key-creation UI can render and submit. This excludes actions
// disabled for Personal API Keys and any generated scope whose object has no UI row.
const API_KEY_CREATION_RENDERABLE_SCOPES = new Set(
    API_SCOPES.flatMap(({ key, disabledActions }) =>
        API_KEY_CREATION_ACTIONS.filter((action) => !disabledActions?.includes(action)).map(
            (action) => `${key}:${action}`
        )
    )
)

// Actions the manual key-creation UI withholds from Personal API Keys
// (e.g. file_system:write, user:write) — see `disabledActions`
// above.
export const API_KEY_CREATION_DISABLED_SCOPES = new Set(
    API_SCOPES.flatMap(({ key, disabledActions }) => (disabledActions ?? []).map((action) => `${key}:${action}`))
)

// Writes a person can choose in a picker but no preset adds. integration:write creates and deletes
// project integrations, which hold stored third-party credentials.
const OPT_IN_ONLY_SCOPES: ReadonlySet<string> = new Set(['integration:write'])

// A preset must not set a level the key picker cannot show, or the picker shows the level on a
// disabled segment. A write on a write-disabled object falls back to read, which write implies on the
// server anyway, and so does an opt-in-only write. A scope with no allowed level is dropped.
export const clampToKeyCreationScopes = (scopes: readonly string[]): string[] => [
    ...new Set(
        scopes.flatMap((scope) => {
            if (API_KEY_CREATION_RENDERABLE_SCOPES.has(scope) && !OPT_IN_ONLY_SCOPES.has(scope)) {
                return [scope]
            }
            const [object, action] = scope.split(':')
            const read = `${object}:read`
            return action === 'write' && API_KEY_CREATION_RENDERABLE_SCOPES.has(read) ? [read] : []
        })
    ),
]

export const AGENT_CLI_API_KEY_SCOPES = clampToKeyCreationScopes(AGENT_USE_CASE_SCOPES)

export const API_KEY_SCOPE_PRESETS: {
    value: string
    label: string
    scopes: string[]
    access_type?: 'all' | 'organizations' | 'teams'
    isCloudOnly?: boolean
}[] = [
    { value: 'local_evaluation', label: 'Local feature flag evaluation', scopes: ['feature_flag:read'] },
    {
        value: 'source_map_upload',
        label: 'Source map upload',
        scopes: ['error_tracking:write'],
    },
    {
        value: 'zapier',
        label: 'Zapier integration',
        scopes: ['action:read', 'query:read', 'project:read', 'organization:read', 'user:read', 'webhook:write'],
    },
    {
        value: 'n8n',
        label: 'n8n integration',
        scopes: ['action:read', 'query:read', 'project:read', 'organization:read', 'user:read', 'webhook:write'],
    },
    { value: 'analytics', label: 'Performing analytics queries', scopes: ['query:read'] },
    { value: 'endpoints', label: 'Endpoint execution', scopes: ['endpoint:read'] },
    {
        value: 'project_management',
        label: 'Project & user management',
        scopes: ['project:write', 'organization:read', 'organization_member:write'],
    },
    {
        value: 'mcp_server',
        label: 'MCP Server',
        // file_system is excluded because the MCP server doesn't request it, not because it's privileged.
        scopes: clampToKeyCreationScopes(
            API_SCOPES.filter(({ key, unprivilegedExcluded }) => !unprivilegedExcluded && key !== 'file_system').map(
                ({ key }) => `${key}:write`
            )
        ),
        access_type: 'all',
    },
    {
        value: 'agent_cli',
        label: 'Agent CLI',
        scopes: AGENT_CLI_API_KEY_SCOPES,
        access_type: 'all',
    },
    {
        value: 'read_only_access',
        label: 'Read-only access',
        scopes: clampToKeyCreationScopes(
            API_SCOPES.filter(({ unprivilegedExcluded }) => !unprivilegedExcluded).map(({ key }) => `${key}:read`)
        ),
    },
    { value: 'all_access', label: 'All access', scopes: ['*'] },
]

export const APIScopeActionLabels: Record<APIScopeAction, string> = {
    read: 'Read',
    write: 'Write',
}

export type ProjectSecretAPIKeyScopePreset = {
    value: string
    label: string
    scopes: string[]
    isCloudOnly?: boolean
}

export const PROJECT_SECRET_API_KEY_SCOPE_PRESETS: ProjectSecretAPIKeyScopePreset[] = [
    { value: 'endpoint_execution', label: 'Endpoint execution', scopes: ['endpoint:read'] },
    { value: 'local_evaluation', label: 'Local feature flag evaluation', scopes: ['feature_flag:read'] },
    { value: 'llm_gateway', label: 'AI gateway access', scopes: ['llm_gateway:read'] },
    { value: 'recipient_preferences', label: 'Set recipient preferences', scopes: ['messaging_preference:write'] },
    { value: 'transactional_email', label: 'Send transactional email', scopes: ['transactional_email:write'] },
]

// The product areas that the scope pickers use to group objects, in display order. Each scope object
// in `ScopeObjectEnumApi` is in exactly one group, except the OAuth-hidden ones, which no picker shows.
// scopes.test.ts fails until a new object has a group.
export type APIScopeGroup = {
    label: string
    objects: APIScopeObject[]
}

export const API_SCOPE_GROUPS: APIScopeGroup[] = SCOPE_GROUPS.map((label) => ({
    label,
    objects: API_SCOPES.filter(({ key }) => SCOPE_DOCS[key].group === label).map(({ key }) => key),
}))

export const OTHER_SCOPE_GROUP_LABEL = 'Other'

// An object that is in no group gets OTHER_SCOPE_GROUP_LABEL, so it still renders.
const SCOPE_GROUP_LABEL_BY_OBJECT: Record<string, string> = Object.fromEntries(
    API_SCOPE_GROUPS.flatMap(({ label, objects }) => objects.map((object) => [object, label]))
)

export const getScopeGroupLabel = (scopeObject: string): string =>
    SCOPE_GROUP_LABEL_BY_OBJECT[scopeObject] ?? OTHER_SCOPE_GROUP_LABEL

// The rows grouped by product area in API_SCOPE_GROUPS order. An object that is in no group goes in
// the "Other" group at the end, so it still shows. A group with no row is left out.
export const groupScopeRows = <Row extends ScopePickerRow>(rows: Row[]): ScopePickerGroup<Row>[] => {
    const rowsByLabel = new Map<string, Row[]>()
    for (const row of rows) {
        const label = getScopeGroupLabel(row.key)
        rowsByLabel.set(label, [...(rowsByLabel.get(label) ?? []), row])
    }
    return [...API_SCOPE_GROUPS.map(({ label }) => label), OTHER_SCOPE_GROUP_LABEL]
        .filter((label) => rowsByLabel.has(label))
        .map((label) => ({ label, rows: rowsByLabel.get(label) ?? [] }))
}

export type ScopeGroupSummary = { label: string; write: number; read: number }

// Counts the objects in each product area that a key can write, or only read, in API_SCOPE_GROUPS order.
// `insight:read` and `insight:write` together count once, as write.
export const summarizeScopesByGroup = (scopes: readonly string[]): ScopeGroupSummary[] => {
    const levelByObject = new Map<string, 'read' | 'write'>()
    for (const scope of scopes) {
        const [object, action] = scope.split(':')
        if (levelByObject.get(object) !== 'write') {
            levelByObject.set(object, action === 'write' ? 'write' : 'read')
        }
    }
    const summaryByLabel = new Map<string, ScopeGroupSummary>()
    for (const [object, level] of levelByObject) {
        const label = getScopeGroupLabel(object)
        const summary = summaryByLabel.get(label) ?? { label, write: 0, read: 0 }
        summary[level] += 1
        summaryByLabel.set(label, summary)
    }
    return [...API_SCOPE_GROUPS.map(({ label }) => label), OTHER_SCOPE_GROUP_LABEL].flatMap((label) => {
        const summary = summaryByLabel.get(label)
        return summary ? [summary] : []
    })
}

export const DEFAULT_OAUTH_SCOPES = ['openid', 'email', 'profile']

export const getScopeDescription = (scope: string): string | undefined => {
    if (scope === '*') {
        return 'Read and write access to all PostHog data'
    }

    if (scope === 'openid') {
        return 'View your User ID'
    }

    if (scope === 'email') {
        return 'View your email address'
    }

    if (scope === 'profile') {
        return 'View basic user account information'
    }

    if (scope === 'introspection') {
        // OAuth-internal scope — never shown to users; list call sites .filter(Boolean) it out.
        return undefined
    }

    const [object, action] = scope.split(':')

    if (!object || !action) {
        return scope
    }

    const actionWord = action === 'write' ? 'Write' : 'Read'

    const scopeObject = API_SCOPES.find((s) => s.key === object)
    if (!scopeObject) {
        // OAuth-hidden scope (e.g. wizard_session, query_performance) — absent from API_SCOPES,
        // so derive a readable label from the raw key rather than surfacing the raw identifier.
        return `${actionWord} access to ${object.replace(/_/g, ' ')}`
    }

    return `${actionWord} access to ${scopeObject.objectPlural}`
}

export const getMinimumEquivalentScopes = (scopes: string[]): string[] => {
    if (scopes.includes('*')) {
        return ['*']
    }

    const highestScopes: Record<string, string> = {}

    for (const scope of scopes) {
        if (['openid', 'email', 'profile'].includes(scope)) {
            highestScopes[scope] = 'default'
            continue
        }

        const [object, action] = scope.split(':')
        if (!object || !action) {
            continue
        }
        if (!highestScopes[object] || (action === 'write' && highestScopes[object] === 'read')) {
            highestScopes[object] = action
        }
    }

    return Object.entries(highestScopes).map(([object, action]) => {
        if (action === 'default') {
            return object
        }
        return `${object}:${action}`
    })
}

/** Convert scopes array format to object format for easier UI manipulation */
export const scopesArrayToObject = (scopes: string[]): Record<string, string> => {
    const result: Record<string, string> = {}
    scopes.forEach((scope) => {
        const [key, action] = scope.split(':')
        if (key && action) {
            result[key] = action
        }
    })
    return result
}

/** Convert scopes object format back to array format for API submission */
export const scopesObjectToArray = (scopesObj: Record<string, string>): string[] => {
    return Object.entries(scopesObj).map(([key, action]) => `${key}:${action}`)
}
