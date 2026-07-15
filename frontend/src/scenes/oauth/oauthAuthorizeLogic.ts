import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { API_SCOPES, DEFAULT_OAUTH_SCOPES, getMinimumEquivalentScopes, getScopeDescription } from 'lib/scopes'
import { getAppContext } from 'lib/utils/getAppContext'
import { userLogic } from 'scenes/userLogic'

import type { OAuthApplicationPublicMetadata, OrganizationBasicType, TeamBasicType, UserType } from '~/types'

import type { oauthAuthorizeLogicType } from './oauthAuthorizeLogicType'

export type OAuthAuthorizationFormValues = {
    scoped_organizations: number[]
    scoped_teams: number[]
    access_type: 'all' | 'organizations' | 'teams'
}

const IDENTITY_SCOPES = ['openid', 'profile', 'email', 'introspection']

const scopeObjectKey = (scope: string): string => (scope === '*' ? '*' : scope.split(':')[0])

export type ScopeAccessLevel = 'none' | 'read' | 'write'

const ACCESS_LEVEL_ORDER: Record<ScopeAccessLevel, number> = { none: 0, read: 1, write: 2 }

const clampAccessLevel = (level: ScopeAccessLevel, min: ScopeAccessLevel, max: ScopeAccessLevel): ScopeAccessLevel => {
    if (ACCESS_LEVEL_ORDER[level] < ACCESS_LEVEL_ORDER[min]) {
        return min
    }
    if (ACCESS_LEVEL_ORDER[level] > ACCESS_LEVEL_ORDER[max]) {
        return max
    }
    return level
}

export type OAuthScopeRow = {
    /** Scope object key (e.g. 'feature_flag'), or '*' for the wildcard. */
    key: string
    /** Human name for the object (e.g. 'Feature flag'). */
    label: string
    /** Full sentence description at the granted level, for the locked (checkmark) list. */
    description: string
    /** Optional extra context from API_SCOPES, shown as an info tooltip. */
    info?: string | JSX.Element
    /** Warning for the currently selected level, if any. */
    warning?: string | JSX.Element
    /** Required floor — the grant can never go below this. 'none' when not required. */
    minLevel: ScopeAccessLevel
    /** Requested ceiling — the grant can never go above what the client asked for. */
    maxLevel: Exclude<ScopeAccessLevel, 'none'>
    /** Current (clamped) selection. */
    value: ScopeAccessLevel
    /** True when minLevel === maxLevel: nothing to choose, rendered as a locked checkmark row. */
    locked: boolean
}

const WILDCARD_LABEL = 'All PostHog data'

// Fallback for scopes absent from API_SCOPES (e.g. server-side scopes the local list lags
// behind) — derive a readable label from the raw key.
const humanizeScopeKey = (key: string): string => {
    const humanized = key.replace(/_/g, ' ')
    return humanized.charAt(0).toUpperCase() + humanized.slice(1)
}

// Required scopes are tracked per object at the action level that's required, so a
// required `obj:read` still lets the read-only toggle downgrade an optional `obj:write`.
export type RequiredLevel = 'read' | 'write'

const requiredLevelsFromScopes = (requiredScopes: string[]): Map<string, RequiredLevel> => {
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

// Mirrors PRIVILEGED_SCOPES + OAUTH_HIDDEN_SCOPE_OBJECTS in posthog/scopes.py: objects
// /authorize can never grant, so the wildcard expansion must skip them or the server
// would reject the whole submit with invalid_scope.
const OAUTH_UNGRANTABLE_OBJECTS: ReadonlySet<string> = new Set(['llm_gateway', 'metrics', 'wizard_session'])

// `*` grants read+write to everything; its read-only form is every grantable object's read
// scope. The server-computed list is authoritative — the local API_SCOPES list both lags
// behind new backend scopes (under-granting) and contains ungrantable ones (over-granting,
// which the server rejects). The local fallback only covers a missing app context.
const wildcardReadScopes = (oauthApplication: OAuthApplicationPublicMetadata | null): string[] =>
    oauthApplication?.wildcard_read_scopes?.length
        ? oauthApplication.wildcard_read_scopes
        : API_SCOPES.filter(({ key }) => !OAUTH_UNGRANTABLE_OBJECTS.has(key)).map(({ key }) => `${key}:read`)

const isNativeProtocol = (url: string): boolean => {
    try {
        const parsed = new URL(url)
        return !['http:', 'https:'].includes(parsed.protocol)
    } catch {
        return false
    }
}

type OAuthAuthorizeResult = { redirectTo: string; isNative: boolean }

const oauthAuthorize = async (
    values: OAuthAuthorizationFormValues & { allow: boolean; scopes: string[] }
): Promise<OAuthAuthorizeResult | null> => {
    try {
        const response = await api.create('/oauth/authorize/', {
            client_id: router.values.searchParams['client_id'],
            redirect_uri: router.values.searchParams['redirect_uri'],
            response_type: router.values.searchParams['response_type'],
            state: router.values.searchParams['state'],
            scope: values.scopes.join(' '),
            code_challenge: router.values.searchParams['code_challenge'],
            code_challenge_method: router.values.searchParams['code_challenge_method'],
            nonce: router.values.searchParams['nonce'],
            claims: router.values.searchParams['claims'],
            scoped_organizations: values.access_type === 'organizations' ? values.scoped_organizations : [],
            scoped_teams: values.access_type === 'teams' ? values.scoped_teams : [],
            access_level:
                values.access_type === 'all' ? 'all' : values.access_type === 'organizations' ? 'organization' : 'team',
            allow: values.allow,
        })

        if (response.redirect_to) {
            return {
                redirectTo: response.redirect_to,
                isNative: isNativeProtocol(response.redirect_to),
            }
        }
        return null
    } catch (error: any) {
        const detail = error?.detail || error?.message || 'Something went wrong while authorizing the application'
        lemonToast.error(detail)
        throw error
    }
}

export const oauthAuthorizeLogic = kea<oauthAuthorizeLogicType>([
    path(['oauth', 'authorize']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        setScopes: (scopes: string[]) => ({ scopes }),
        setScopeAccess: (scopeObject: string, level: ScopeAccessLevel) => ({ scopeObject, level }),
        setAllScopeAccess: (level: ScopeAccessLevel) => ({ level }),
        setRequiredAccessLevel: (requiredAccessLevel: 'organization' | 'team' | null) => ({ requiredAccessLevel }),
        setTeamHint: (teamId: number | null) => ({ teamId }),
        setScopesWereDefaulted: (scopesWereDefaulted: boolean) => ({ scopesWereDefaulted }),
        setIsMcpResource: (isMcpResource: boolean) => ({ isMcpResource }),
        cancel: () => ({}),
        setCanceling: (canceling: boolean) => ({ canceling }),
        setAuthorizationComplete: (complete: boolean) => ({ complete }),
        setRedirecting: (redirectUrl: string) => ({ redirectUrl }),
        setSelectedOrganization: (organizationId: string, preferredTeamId?: number) => ({
            organizationId,
            preferredTeamId,
        }),
        setShowCreateProject: (show: boolean) => ({ show }),
        createNewProject: (name: string) => ({ name }),
        setNewProjectLoading: (loading: boolean) => ({ loading }),
    }),
    loaders({
        allTeams: [
            null as TeamBasicType[] | null,
            {
                loadAllTeams: async () => {
                    const user = userLogic.values.user
                    if (!user?.organizations?.length) {
                        return await api.loadPaginatedResults('api/projects')
                    }
                    const results = await Promise.all(
                        user.organizations.map((org) =>
                            api.loadPaginatedResults<TeamBasicType>(`api/organizations/${org.id}/projects`)
                        )
                    )
                    return results.flat()
                },
            },
        ],
        oauthApplication: [
            null as OAuthApplicationPublicMetadata | null,
            {
                loadOAuthApplication: async () => {
                    // The authorize view injects the application metadata into the page
                    // context after resolving the client_id (including CIMD clients).
                    // No API call needed.
                    const preloaded = getAppContext()?.oauth_application
                    return preloaded ?? null
                },
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        cancel: async () => {
            actions.setCanceling(true)
            try {
                const result = await oauthAuthorize({
                    scoped_organizations: values.oauthAuthorization.scoped_organizations,
                    scoped_teams: values.oauthAuthorization.scoped_teams,
                    access_type: values.oauthAuthorization.access_type,
                    allow: false,
                    scopes: values.scopes,
                })
                if (result) {
                    location.href = result.redirectTo
                }
            } finally {
                actions.setCanceling(false)
            }
        },
        createNewProject: async ({ name }) => {
            actions.setNewProjectLoading(true)
            try {
                const orgId = values.selectedOrganization
                const endpoint = orgId ? `api/organizations/${orgId}/projects/` : 'api/projects/'
                await api.create(endpoint, { name })
                lemonToast.success(`Project "${name}" created`)
                actions.setShowCreateProject(false)
                // Remember existing team IDs so we can find the new one after reload
                const existingIds = new Set((values.allTeams ?? []).map((t) => t.id))
                await oauthAuthorizeLogic.asyncActions.loadAllTeams()
                // Find the newly created team and auto-select it
                const newTeam = (values.allTeams ?? []).find(
                    (t) => !existingIds.has(t.id) && t.organization === values.selectedOrganization
                )
                if (newTeam) {
                    actions.setOauthAuthorizationValue('scoped_teams', [newTeam.id])
                }
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to create project')
            } finally {
                actions.setNewProjectLoading(false)
            }
        },
    })),
    reducers({
        scopes: [
            [] as string[],
            {
                setScopes: (_, { scopes }) => scopes,
            },
        ],
        // The user's picks. `bulk` is the last bulk action (Select all / Read-only / Deselect
        // all); `overrides` are per-object picks made after it. Absent entries default to the
        // requested ceiling, and every pick is clamped to [required floor, requested ceiling]
        // in scopeRows, so bulk actions can apply one level blindly to heterogeneous rows.
        scopeAccessSelections: [
            { bulk: null, overrides: {} } as {
                bulk: ScopeAccessLevel | null
                overrides: Record<string, ScopeAccessLevel>
            },
            {
                setScopeAccess: (state, { scopeObject, level }) => ({
                    ...state,
                    overrides: { ...state.overrides, [scopeObject]: level },
                }),
                setAllScopeAccess: (_, { level }) => ({ bulk: level, overrides: {} }),
                setScopes: () => ({ bulk: null, overrides: {} }),
            },
        ],
        requiredAccessLevel: [
            null as 'organization' | 'team' | null,
            {
                setRequiredAccessLevel: (_, { requiredAccessLevel }) => requiredAccessLevel,
            },
        ],
        scopesWereDefaulted: [
            false,
            {
                setScopesWereDefaulted: (_, { scopesWereDefaulted }) => scopesWereDefaulted,
            },
        ],
        isMcpResource: [
            false,
            {
                setIsMcpResource: (_, { isMcpResource }) => isMcpResource,
            },
        ],
        isCanceling: [
            false,
            {
                setCanceling: (_, { canceling }) => canceling,
            },
        ],
        authorizationComplete: [
            false,
            {
                setAuthorizationComplete: (_, { complete }) => complete,
            },
        ],
        isRedirecting: [
            false,
            {
                setRedirecting: () => true,
            },
        ],
        redirectUrl: [
            '',
            {
                setRedirecting: (_, { redirectUrl }) => redirectUrl,
            },
        ],
        selectedOrganization: [
            null as string | null,
            {
                setSelectedOrganization: (_, { organizationId }) => organizationId,
            },
        ],
        teamHint: [
            null as number | null,
            {
                setTeamHint: (_, { teamId }) => teamId,
            },
        ],
        showCreateProject: [
            false,
            {
                setShowCreateProject: (_, { show }) => show,
            },
        ],
        newProjectLoading: [
            false,
            {
                setNewProjectLoading: (_, { loading }) => loading,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setRequiredAccessLevel: ({ requiredAccessLevel }) => {
            if (requiredAccessLevel === 'organization') {
                actions.setOauthAuthorizationValue('access_type', 'organizations')
            } else if (requiredAccessLevel === 'team') {
                actions.setOauthAuthorizationValue('access_type', 'teams')
                // With a team_id hint pending, let it drive org+project selection once
                // teams load — don't pre-select the user's current org/team, or a CTA
                // link could authorize the wrong project before the hint resolves. The
                // empty project keeps the submit blocked until the hint fills it in.
                if (!values.teamHint) {
                    const user = userLogic.values.user
                    if (user?.organization?.id) {
                        actions.setSelectedOrganization(user.organization.id, user?.team?.id)
                    }
                }
            }
        },
        setSelectedOrganization: ({ preferredTeamId }) => {
            // Auto-select the preferred team or the first team in the org
            const teams = values.sortedTeams
            const orgId = values.selectedOrganization
            if (teams && orgId) {
                const orgTeams = teams.filter((t) => t.organization === orgId)
                const match = preferredTeamId ? orgTeams.find((t) => t.id === preferredTeamId) : orgTeams[0]
                actions.setOauthAuthorizationValue('scoped_teams', match ? [match.id] : [])
            } else {
                // Teams not loaded yet — loadAllTeamsSuccess will handle it
                actions.setOauthAuthorizationValue('scoped_teams', preferredTeamId ? [preferredTeamId] : [])
            }
        },
        loadAllTeamsSuccess: () => {
            const teams = values.sortedTeams
            if (!teams) {
                return
            }
            // A team_id hint from the authorize URL (e.g. the wizard's --project-id) wins:
            // pre-select that project and its org so the user just clicks Authorize. We only
            // honor it if the user has access to that team (it's in their loaded teams), and
            // consume it once — so it can't override a later manual change or a project the
            // user creates here (both also re-fire this listener).
            if (values.teamHint) {
                const hinted = teams.find((t) => t.id === values.teamHint)
                actions.setTeamHint(null)
                if (hinted && values.requiredAccessLevel === 'team') {
                    actions.setSelectedOrganization(hinted.organization, hinted.id)
                    return
                }
                // Hint didn't resolve (inaccessible team, or not a team-level grant). Fall
                // back to the user's current org/team — setRequiredAccessLevel skipped this
                // while the hint was pending, so without it the screen would be left empty.
                if (values.requiredAccessLevel === 'team' && !values.selectedOrganization) {
                    const user = userLogic.values.user
                    if (user?.organization?.id) {
                        actions.setSelectedOrganization(user.organization.id, user?.team?.id)
                        return
                    }
                }
            }
            // After teams load, auto-select first project if org is set but no project selected
            const orgId = values.selectedOrganization
            const currentTeams = values.oauthAuthorization.scoped_teams
            if (orgId && (!currentTeams || currentTeams.length === 0)) {
                const orgTeams = teams.filter((t) => t.organization === orgId)
                if (orgTeams.length > 0) {
                    actions.setOauthAuthorizationValue('scoped_teams', [orgTeams[0].id])
                }
            }
        },
    })),
    forms(({ actions }) => ({
        oauthAuthorization: {
            defaults: {
                scoped_organizations: [],
                scoped_teams: [],
                access_type: 'all',
            } as OAuthAuthorizationFormValues,
            errors: ({ access_type, scoped_organizations, scoped_teams }: OAuthAuthorizationFormValues) => ({
                access_type: !access_type ? ('Select access mode' as any) : undefined,
                scoped_organizations:
                    access_type === 'organizations' && !scoped_organizations?.length
                        ? ('Select at least one organization' as any)
                        : undefined,
                scoped_teams:
                    access_type === 'teams' && !scoped_teams?.length
                        ? ('Select at least one project' as any)
                        : undefined,
            }),
            submit: async (values: OAuthAuthorizationFormValues) => {
                const scopes = oauthAuthorizeLogic.values.effectiveScopes
                const result = await oauthAuthorize({
                    ...values,
                    allow: true,
                    scopes,
                })
                if (!result) {
                    return
                }
                // Swap the form for a "Redirecting…" view so the user sees progress
                // while the browser navigates — for HTTP loopback redirects (Cursor,
                // Claude Code, etc.) the browser may sit waiting for the local
                // listener to respond, which makes the original screen feel hung.
                actions.setRedirecting(result.redirectTo)
                location.href = result.redirectTo
                if (result.isNative) {
                    // Native protocol handlers (vscode://, cursor://, etc.) don't
                    // navigate the browser away; show success after a brief delay.
                    setTimeout(() => actions.setAuthorizationComplete(true), 100)
                }
            },
        },
    })),
    selectors(() => ({
        allOrganizations: [
            (s) => [s.user],
            (user: UserType): OrganizationBasicType[] => {
                return user?.organizations ?? []
            },
        ],
        sortedTeams: [
            (s) => [s.allTeams, s.allOrganizations, s.user],
            (
                teams: TeamBasicType[] | null,
                organizations: OrganizationBasicType[],
                user: UserType
            ): TeamBasicType[] | null => {
                if (!teams) {
                    return null
                }
                const currentTeamId = user?.team?.id
                const orgNameMap = new Map(organizations.map((org) => [org.id, org.name]))
                return [...teams].sort((a, b) => {
                    // Current team always comes first
                    if (a.id === currentTeamId) {
                        return -1
                    }
                    if (b.id === currentTeamId) {
                        return 1
                    }
                    const orgA = orgNameMap.get(a.organization) ?? ''
                    const orgB = orgNameMap.get(b.organization) ?? ''
                    if (orgA !== orgB) {
                        return orgA.localeCompare(orgB)
                    }
                    return a.name.localeCompare(b.name)
                })
            },
        ],
        filteredTeams: [
            (s) => [s.sortedTeams, s.selectedOrganization],
            (teams: TeamBasicType[] | null, selectedOrg: string | null): TeamBasicType[] | null => {
                if (!teams || !selectedOrg) {
                    return teams
                }
                return teams.filter((t) => t.organization === selectedOrg)
            },
        ],
        identityScopeDescriptions: [
            (s) => [s.scopes],
            (scopes: string[]): string[] =>
                scopes
                    .filter((scope) => IDENTITY_SCOPES.includes(scope))
                    .map(getScopeDescription)
                    .filter(Boolean) as string[],
        ],
        requiredScopeLevels: [
            (s) => [s.oauthApplication],
            (oauthApplication: OAuthApplicationPublicMetadata | null): Map<string, RequiredLevel> =>
                requiredLevelsFromScopes(oauthApplication?.required_scopes ?? []),
        ],
        // Requested plus required resource scopes, collapsed to the highest action per
        // object. Both the rows and the grant derive from this one set, so the consent
        // screen always displays exactly what authorizing will grant — required scopes
        // the client didn't request get a visible (locked) row, never a silent grant.
        consentResourceScopes: [
            (s) => [s.scopes, s.oauthApplication],
            (scopes: string[], oauthApplication: OAuthApplicationPublicMetadata | null): string[] => {
                const required = (oauthApplication?.required_scopes ?? []).filter(
                    (scope) => scope.includes(':') || scope === '*'
                )
                return getMinimumEquivalentScopes([...scopes, ...required]).filter(
                    (scope) => scope.includes(':') || scope === '*'
                )
            },
        ],
        // One row per scope object. The requested set caps the ceiling, the required set
        // sets the floor, and the user's selection is clamped between the two — so no pick
        // (including bulk actions) can grant more than requested or less than required.
        scopeRows: [
            (s) => [s.consentResourceScopes, s.scopeAccessSelections, s.requiredScopeLevels],
            (
                consentResourceScopes: string[],
                scopeAccessSelections: { bulk: ScopeAccessLevel | null; overrides: Record<string, ScopeAccessLevel> },
                requiredScopeLevels: Map<string, RequiredLevel>
            ): OAuthScopeRow[] => {
                const rows = consentResourceScopes.map((scope): OAuthScopeRow => {
                    const key = scopeObjectKey(scope)
                    const maxLevel: 'read' | 'write' = scope === '*' || scope.endsWith(':write') ? 'write' : 'read'
                    const minLevel: ScopeAccessLevel = requiredScopeLevels.get(key) ?? 'none'
                    const selected = scopeAccessSelections.overrides[key] ?? scopeAccessSelections.bulk ?? maxLevel
                    const value = clampAccessLevel(selected, minLevel, maxLevel)
                    const apiScope = key === '*' ? undefined : API_SCOPES.find((s) => s.key === key)
                    const grantedScope = scope === '*' && value === 'write' ? '*' : `${key}:${value}`
                    return {
                        key,
                        label: key === '*' ? WILDCARD_LABEL : (apiScope?.objectName ?? humanizeScopeKey(key)),
                        description: getScopeDescription(grantedScope) ?? grantedScope,
                        info: apiScope?.info,
                        warning: value === 'none' ? undefined : apiScope?.warnings?.[value],
                        minLevel,
                        maxLevel,
                        value,
                        locked: minLevel === maxLevel,
                    }
                })
                return rows.sort((a, b) => a.label.localeCompare(b.label))
            },
        ],
        // Locked rows (required at exactly the requested level) render as a plain checkmark
        // list — there is nothing to choose — while adjustable rows get an access selector.
        requiredScopeRows: [
            (s) => [s.scopeRows],
            (scopeRows: OAuthScopeRow[]): OAuthScopeRow[] => scopeRows.filter((row) => row.locked),
        ],
        adjustableScopeRows: [
            (s) => [s.scopeRows],
            (scopeRows: OAuthScopeRow[]): OAuthScopeRow[] => scopeRows.filter((row) => !row.locked),
        ],
        allScopesRequired: [
            (s) => [s.scopeRows],
            (scopeRows: OAuthScopeRow[]): boolean => scopeRows.length > 0 && scopeRows.every((row) => row.locked),
        ],
        // Only offer the bulk read-only action when it would change something — i.e. at least
        // one adjustable row can sit at write level.
        showReadOnlyBulkAction: [
            (s) => [s.adjustableScopeRows],
            (adjustableScopeRows: OAuthScopeRow[]): boolean =>
                adjustableScopeRows.some((row) => row.maxLevel === 'write'),
        ],
        effectiveScopes: [
            (s) => [s.scopes, s.scopeRows, s.oauthApplication],
            (
                scopes: string[],
                scopeRows: OAuthScopeRow[],
                oauthApplication: OAuthApplicationPublicMetadata | null
            ): string[] => {
                const identity = scopes.filter((scope) => IDENTITY_SCOPES.includes(scope))
                const resources = scopeRows.flatMap((row) => {
                    if (row.value === 'none') {
                        return []
                    }
                    if (row.key === '*') {
                        return row.value === 'write' ? ['*'] : wildcardReadScopes(oauthApplication)
                    }
                    return [`${row.key}:${row.value}`]
                })
                // Also grant the required strings verbatim: collapsing read+write pairs above
                // could otherwise drop a literal entry the server's set-difference check expects.
                const required = (oauthApplication?.required_scopes ?? []).filter(
                    (scope) => scope.includes(':') || scope === '*'
                )
                return Array.from(new Set([...identity, ...resources, ...required]))
            },
        ],
        redirectDomain: [
            (s) => [s.oauthApplication],
            (): string => {
                const redirectUri = router.values.searchParams['redirect_uri'] as string
                if (!redirectUri) {
                    return ''
                }
                try {
                    const url = new URL(redirectUri)
                    return url.hostname
                } catch {
                    return ''
                }
            },
        ],
    })),
    urlToAction(({ actions }) => {
        const handleAuthorize = (_: Record<string, any>, searchParams: Record<string, any>): void => {
            const requestedScopes = searchParams['scope']?.split(' ')?.filter((scope: string) => scope.length) ?? []
            const oauthMcpConsent = getAppContext()?.oauth_mcp_consent

            const scopesWereDefaulted = requestedScopes.length === 0

            const rawRequiredAccessLevel = searchParams['required_access_level'] as 'organization' | 'project' | null
            const requiredAccessLevel = rawRequiredAccessLevel === 'project' ? 'team' : rawRequiredAccessLevel

            // Optional project to pre-select on the consent screen (e.g. the wizard's
            // `--project-id`). Honored only when the user has access to it; otherwise ignored.
            const teamIdParam = Number(searchParams['team_id'])
            const teamHint = Number.isInteger(teamIdParam) && teamIdParam > 0 ? teamIdParam : null

            actions.setScopesWereDefaulted(scopesWereDefaulted)
            actions.setTeamHint(teamHint)
            actions.setRequiredAccessLevel(requiredAccessLevel || null)
            actions.loadOAuthApplication()
            actions.loadAllTeams()

            if (scopesWereDefaulted && oauthMcpConsent?.is_mcp_resource) {
                actions.setIsMcpResource(true)
                actions.setScopes(oauthMcpConsent.scopes ?? DEFAULT_OAUTH_SCOPES)
            } else if (scopesWereDefaulted) {
                actions.setIsMcpResource(false)
                actions.setScopes(DEFAULT_OAUTH_SCOPES)
            } else {
                actions.setIsMcpResource(false)
                actions.setScopes(requestedScopes)
            }
        }

        return {
            '/oauth/authorize': handleAuthorize,
            '/oauth/authorize/': handleAuthorize,
        }
    }),
])
