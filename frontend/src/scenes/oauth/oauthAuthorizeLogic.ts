import { decode } from 'he'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import {
    API_SCOPES,
    DEFAULT_OAUTH_SCOPES,
    MCP_SERVER_OAUTH_SCOPES,
    getMinimumEquivalentScopes,
    getScopeDescription,
} from 'lib/scopes'
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

const WILDCARD_READ_DESCRIPTION = 'Read access to all PostHog data'
const WILDCARD_LABEL = 'All PostHog data'

// Per-resource access level the user grants at consent. `none` declines the resource entirely.
export type ScopeAction = 'none' | 'read' | 'write'
const ACTION_RANK: Record<ScopeAction, number> = { none: 0, read: 1, write: 2 }

// Objects whose read/write action can't be granted (mirrors `disabledActions` in lib/scopes),
// so the consent picker doesn't offer a level the server would reject.
const DISABLED_ACTIONS_BY_OBJECT: Map<string, ReadonlySet<'read' | 'write'>> = new Map(
    API_SCOPES.filter(({ disabledActions }) => disabledActions?.length).map(({ key, disabledActions }) => [
        key,
        new Set(disabledActions),
    ])
)

// A resource object the client asked for, resolved to its grantable floor/ceiling. `ceiling` is
// the highest action the client requested (or required); `floor` is the lowest the user may pick
// (a required scope pins it above `none`). The available flags gate the segmented picker options.
export type ScopeObjectDescriptor = {
    key: string
    isWildcard: boolean
    floor: ScopeAction
    ceiling: ScopeAction
    noneAvailable: boolean
    readAvailable: boolean
    writeAvailable: boolean
    label: string
    info?: string | JSX.Element
    warnings?: Partial<Record<'read' | 'write', string | JSX.Element>>
}

const availableActions = (obj: ScopeObjectDescriptor): ScopeAction[] => {
    const available: ScopeAction[] = []
    if (obj.noneAvailable) {
        available.push('none')
    }
    if (obj.readAvailable) {
        available.push('read')
    }
    if (obj.writeAvailable) {
        available.push('write')
    }
    return available
}

// Resolve the effective action for an object: the user's override if it's a valid option, else the
// requested ceiling, clamped into the available range so it never drops below a required floor.
const resolveScopeAction = (obj: ScopeObjectDescriptor, override: ScopeAction | undefined): ScopeAction => {
    const available = availableActions(obj)
    const candidate = override ?? obj.ceiling
    if (available.includes(candidate)) {
        return candidate
    }
    // availableActions returns ascending rank, so the highest option at or below the candidate is
    // the clamped value; if the candidate is below every option, fall to the lowest available.
    let best = available[0] ?? obj.floor
    for (const action of available) {
        if (ACTION_RANK[action] <= ACTION_RANK[candidate]) {
            best = action
        }
    }
    return best
}

const scopeObjectLabel = (key: string): string => {
    if (key === '*') {
        return WILDCARD_LABEL
    }
    const scopeObject = API_SCOPES.find((s) => s.key === key)
    if (scopeObject) {
        return scopeObject.objectName
    }
    // OAuth-hidden object absent from API_SCOPES — derive a readable label from the raw key.
    const words = key.replace(/_/g, ' ')
    return words.charAt(0).toUpperCase() + words.slice(1)
}

// Required scopes are tracked per object at the action level that's required, so a
// required `obj:read` still lets read-only downgrade an optional `obj:write`.
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
        setScopeAction: (scopeObject: string, action: ScopeAction) => ({ scopeObject, action }),
        setScopeActionOverrides: (overrides: Record<string, ScopeAction>) => ({ overrides }),
        selectAllScopes: () => ({}),
        deselectAllScopes: () => ({}),
        setReadOnlyScopes: () => ({}),
        setRequiredAccessLevel: (requiredAccessLevel: 'organization' | 'team' | null) => ({ requiredAccessLevel }),
        setTeamHint: (teamId: number | null) => ({ teamId }),
        setScopesWereDefaulted: (scopesWereDefaulted: boolean) => ({ scopesWereDefaulted }),
        setIsMcpResource: (isMcpResource: boolean) => ({ isMcpResource }),
        loadResourceScopes: (resourceUrl: string) => ({ resourceUrl }),
        setResourceScopesLoading: (loading: boolean) => ({ loading }),
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
        selectAllScopes: () => {
            // Clearing overrides restores each object to its requested ceiling (grant everything).
            actions.setScopeActionOverrides({})
        },
        deselectAllScopes: () => {
            // Drop every object to its floor: `none` for optional scopes, the required level otherwise.
            const overrides: Record<string, ScopeAction> = {}
            for (const obj of values.scopeObjects) {
                overrides[obj.key] = obj.floor
            }
            actions.setScopeActionOverrides(overrides)
        },
        setReadOnlyScopes: () => {
            // Downgrade every object to read where allowed; required-write scopes stay at write.
            const overrides: Record<string, ScopeAction> = {}
            for (const obj of values.scopeObjects) {
                overrides[obj.key] = resolveScopeAction(obj, 'read')
            }
            actions.setScopeActionOverrides(overrides)
        },
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
        loadResourceScopes: async ({ resourceUrl }) => {
            // Fetch scopes from the OAuth Protected Resource Metadata endpoint
            // Per RFC 9728, the metadata is at /.well-known/oauth-protected-resource
            actions.setResourceScopesLoading(true)
            try {
                const url = new URL(resourceUrl)
                const metadataUrl = `${url.origin}/.well-known/oauth-protected-resource`
                const response = await fetch(metadataUrl)
                if (!response.ok) {
                    throw new Error(`Failed to fetch protected resource metadata: ${response.status}`)
                }
                const metadata = await response.json()
                if (metadata.scopes_supported && Array.isArray(metadata.scopes_supported)) {
                    actions.setScopes(metadata.scopes_supported)
                    return
                }
            } catch (e) {
                // Fall back to hardcoded scopes on any error
                console.warn('Failed to fetch resource scopes, using fallback:', e)
            } finally {
                actions.setResourceScopesLoading(false)
            }
            // Fallback to hardcoded MCP scopes
            actions.setScopes(MCP_SERVER_OAUTH_SCOPES)
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
        // Per-object user overrides of the requested access level. Empty means "grant exactly what
        // was requested" (each object defaults to its requested ceiling). Reset when scopes reload.
        scopeActionOverrides: [
            {} as Record<string, ScopeAction>,
            {
                setScopeAction: (state, { scopeObject, action }) => ({ ...state, [scopeObject]: action }),
                setScopeActionOverrides: (_, { overrides }) => overrides,
                setScopes: () => ({}),
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
        resourceScopesLoading: [
            false,
            {
                setResourceScopesLoading: (_, { loading }) => loading,
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
        appName: [
            (s) => [s.oauthApplication],
            (oauthApplication: OAuthApplicationPublicMetadata | null): string =>
                // The name is HTML-escaped at ingestion (posthog/api/oauth/client_name.py); decode it
                // so disabled reasons read as plain text instead of showing entities like "&amp;".
                oauthApplication ? decode(oauthApplication.name) : 'this application',
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
        // Each requested (or required) resource object resolved to its grantable floor/ceiling. This
        // is the single source of truth the rows, the effective grant, and the bulk controls derive
        // from, so the consent screen always displays exactly what authorizing will grant.
        scopeObjects: [
            (s) => [s.consentResourceScopes, s.requiredScopeLevels],
            (
                consentResourceScopes: string[],
                requiredScopeLevels: Map<string, RequiredLevel>
            ): ScopeObjectDescriptor[] =>
                consentResourceScopes.map((scope) => {
                    const isWildcard = scope === '*'
                    const key = scopeObjectKey(scope)
                    const requiredLevel = requiredScopeLevels.get(key)
                    const floor: ScopeAction = requiredLevel ?? 'none'
                    const ceiling: ScopeAction = isWildcard || scope.endsWith(':write') ? 'write' : 'read'
                    const disabled = DISABLED_ACTIONS_BY_OBJECT.get(key)
                    const scopeObject = isWildcard ? undefined : API_SCOPES.find((sc) => sc.key === key)
                    return {
                        key,
                        isWildcard,
                        floor,
                        ceiling,
                        noneAvailable: floor === 'none',
                        // Read is offered whenever it isn't below a required-write floor and the object
                        // actually supports a read action.
                        readAvailable: floor !== 'write' && !disabled?.has('read'),
                        writeAvailable: ceiling === 'write' && !disabled?.has('write'),
                        label: scopeObjectLabel(key),
                        info: scopeObject?.info,
                        warnings: scopeObject?.warnings,
                    }
                }),
        ],
        // The action currently granted per object, applying the user's overrides on top of the
        // requested defaults (clamped so a required floor can never be dropped below).
        currentScopeActions: [
            (s) => [s.scopeObjects, s.scopeActionOverrides],
            (
                scopeObjects: ScopeObjectDescriptor[],
                scopeActionOverrides: Record<string, ScopeAction>
            ): Record<string, ScopeAction> => {
                const result: Record<string, ScopeAction> = {}
                for (const obj of scopeObjects) {
                    result[obj.key] = resolveScopeAction(obj, scopeActionOverrides[obj.key])
                }
                return result
            },
        ],
        scopeRows: [
            (s) => [s.scopeObjects, s.currentScopeActions, s.appName],
            (
                scopeObjects: ScopeObjectDescriptor[],
                currentScopeActions: Record<string, ScopeAction>,
                appName: string
            ): {
                key: string
                label: string
                value: ScopeAction
                required: boolean
                hasChoice: boolean
                info?: string | JSX.Element
                warning?: string | JSX.Element
                noneDisabledReason?: string
                readDisabledReason?: string
                writeDisabledReason?: string
                description: string
            }[] =>
                scopeObjects.map((obj) => {
                    const value = currentScopeActions[obj.key]
                    const description = obj.isWildcard
                        ? value === 'read'
                            ? WILDCARD_READ_DESCRIPTION
                            : (getScopeDescription('*') ?? '*')
                        : (getScopeDescription(`${obj.key}:${value}`) ?? `${obj.key}:${value}`)
                    return {
                        key: obj.key,
                        label: obj.label,
                        value,
                        required: obj.floor !== 'none',
                        hasChoice: availableActions(obj).length >= 2,
                        info: obj.info,
                        warning: value === 'read' || value === 'write' ? obj.warnings?.[value] : undefined,
                        noneDisabledReason: obj.noneAvailable ? undefined : `Required by ${appName}`,
                        readDisabledReason: obj.readAvailable
                            ? undefined
                            : obj.floor === 'write'
                              ? `${appName} requires write access`
                              : "Read access isn't available for this resource",
                        writeDisabledReason: obj.writeAvailable ? undefined : `${appName} didn't request write access`,
                        description,
                    }
                }),
        ],
        // When no row offers a choice, the user has nothing to toggle, so the consent screen renders
        // a plain locked list instead of segmented buttons that imply a choice.
        allScopesLocked: [
            (s) => [s.scopeRows],
            (scopeRows: { hasChoice: boolean }[]): boolean =>
                scopeRows.length > 0 && scopeRows.every((row) => !row.hasChoice),
        ],
        // Offer the "Read-only" bulk control only when a currently-granted write can be downgraded.
        canSetReadOnly: [
            (s) => [s.scopeObjects, s.currentScopeActions],
            (scopeObjects: ScopeObjectDescriptor[], currentScopeActions: Record<string, ScopeAction>): boolean =>
                scopeObjects.some((obj) => obj.readAvailable && currentScopeActions[obj.key] === 'write'),
        ],
        allScopesGranted: [
            (s) => [s.scopeObjects, s.currentScopeActions],
            (scopeObjects: ScopeObjectDescriptor[], currentScopeActions: Record<string, ScopeAction>): boolean =>
                scopeObjects.length > 0 && scopeObjects.every((obj) => currentScopeActions[obj.key] === obj.ceiling),
        ],
        allScopesDenied: [
            (s) => [s.scopeObjects, s.currentScopeActions],
            (scopeObjects: ScopeObjectDescriptor[], currentScopeActions: Record<string, ScopeAction>): boolean =>
                scopeObjects.length > 0 && scopeObjects.every((obj) => currentScopeActions[obj.key] === obj.floor),
        ],
        effectiveScopes: [
            (s) => [s.scopes, s.scopeObjects, s.currentScopeActions, s.oauthApplication],
            (
                scopes: string[],
                scopeObjects: ScopeObjectDescriptor[],
                currentScopeActions: Record<string, ScopeAction>,
                oauthApplication: OAuthApplicationPublicMetadata | null
            ): string[] => {
                const identity = scopes.filter((scope) => IDENTITY_SCOPES.includes(scope))
                const resources = scopeObjects.flatMap((obj) => {
                    const value = currentScopeActions[obj.key]
                    if (value === 'none') {
                        return []
                    }
                    if (obj.isWildcard) {
                        return value === 'read' ? wildcardReadScopes(oauthApplication) : ['*']
                    }
                    return [`${obj.key}:${value}`]
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
            const resourceParam = searchParams['resource'] as string | undefined

            // Check if this is an MCP server request with no scopes specified
            // Per MCP spec, when clients don't specify scopes, they should use all scopes_supported
            // from the Protected Resource Metadata. We default to MCP scopes for known MCP resources.
            let isMcpResource = false
            if (resourceParam) {
                try {
                    const resourceUrl = new URL(resourceParam)
                    // Strict hostname check to prevent URL manipulation attacks
                    isMcpResource = resourceUrl.hostname === 'mcp.posthog.com'
                } catch {
                    // Invalid URL, not an MCP resource
                }
            }
            const scopesWereDefaulted = requestedScopes.length === 0

            const rawRequiredAccessLevel = searchParams['required_access_level'] as 'organization' | 'project' | null
            const requiredAccessLevel = rawRequiredAccessLevel === 'project' ? 'team' : rawRequiredAccessLevel

            // Optional project to pre-select on the consent screen (e.g. the wizard's
            // `--project-id`). Honored only when the user has access to it; otherwise ignored.
            const teamIdParam = Number(searchParams['team_id'])
            const teamHint = Number.isInteger(teamIdParam) && teamIdParam > 0 ? teamIdParam : null

            actions.setScopesWereDefaulted(scopesWereDefaulted)
            actions.setIsMcpResource(isMcpResource)
            actions.setTeamHint(teamHint)
            actions.setRequiredAccessLevel(requiredAccessLevel || null)
            actions.loadOAuthApplication()
            actions.loadAllTeams()

            if (scopesWereDefaulted && isMcpResource && resourceParam) {
                // Fetch scopes dynamically from the protected resource metadata
                actions.loadResourceScopes(resourceParam)
            } else if (scopesWereDefaulted) {
                // Fallback to minimal OIDC scopes for non-MCP clients
                actions.setScopes(DEFAULT_OAUTH_SCOPES)
            } else {
                actions.setScopes(requestedScopes)
            }
        }

        return {
            '/oauth/authorize': handleAuthorize,
            '/oauth/authorize/': handleAuthorize,
        }
    }),
])
