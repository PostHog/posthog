import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import {
    DEFAULT_OAUTH_SCOPES,
    MCP_SERVER_OAUTH_SCOPES,
    getMinimumEquivalentScopes,
    getScopeDescription,
} from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import type { OAuthApplicationPublicMetadata, OrganizationBasicType, TeamBasicType, UserType } from '~/types'

import type { oauthAuthorizeLogicType } from './oauthAuthorizeLogicType'

export type OAuthAuthorizationFormValues = {
    scoped_organizations: number[]
    scoped_teams: number[]
    access_type: 'all' | 'organizations' | 'teams'
}

const isNativeProtocol = (url: string): boolean => {
    try {
        const parsed = new URL(url)
        return !['http:', 'https:'].includes(parsed.protocol)
    } catch {
        return false
    }
}

const oauthAuthorize = async (
    values: OAuthAuthorizationFormValues & { allow: boolean; scopes: string[] },
    onNativeRedirectComplete?: () => void
): Promise<void> => {
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
            const isNative = isNativeProtocol(response.redirect_to)
            location.href = response.redirect_to

            if (isNative && onNativeRedirectComplete) {
                // Small delay to ensure redirect is initiated before showing success
                setTimeout(() => onNativeRedirectComplete(), 100)
            }
        }
    } catch (error: any) {
        lemonToast.error('Something went wrong while authorizing the application')
        throw error
    }

    return
}

export const oauthAuthorizeLogic = kea<oauthAuthorizeLogicType>([
    path(['oauth', 'authorize']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        setScopes: (scopes: string[]) => ({ scopes }),
        setRequiredAccessLevel: (requiredAccessLevel: 'organization' | 'team' | null) => ({ requiredAccessLevel }),
        setScopesWereDefaulted: (scopesWereDefaulted: boolean) => ({ scopesWereDefaulted }),
        setIsMcpResource: (isMcpResource: boolean) => ({ isMcpResource }),
        loadResourceScopes: (resourceUrl: string) => ({ resourceUrl }),
        setResourceScopesLoading: (loading: boolean) => ({ loading }),
        cancel: () => ({}),
        setCanceling: (canceling: boolean) => ({ canceling }),
        setAuthorizationComplete: (complete: boolean) => ({ complete }),
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
                    return await api.oauthApplication.getPublicMetadata(
                        router.values.searchParams['client_id'] as string
                    )
                },
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        cancel: async () => {
            actions.setCanceling(true)
            try {
                await oauthAuthorize({
                    scoped_organizations: values.oauthAuthorization.scoped_organizations,
                    scoped_teams: values.oauthAuthorization.scoped_teams,
                    access_type: values.oauthAuthorization.access_type,
                    allow: false,
                    scopes: values.scopes,
                })
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
        selectedOrganization: [
            null as string | null,
            {
                setSelectedOrganization: (_, { organizationId }) => organizationId,
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
                const user = userLogic.values.user
                if (user?.organization?.id) {
                    actions.setSelectedOrganization(user.organization.id, user?.team?.id)
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
            // After teams load, auto-select first project if org is set but no project selected
            const orgId = values.selectedOrganization
            const currentTeams = values.oauthAuthorization.scoped_teams
            if (orgId && (!currentTeams || currentTeams.length === 0)) {
                const teams = values.sortedTeams
                if (teams) {
                    const orgTeams = teams.filter((t) => t.organization === orgId)
                    if (orgTeams.length > 0) {
                        actions.setOauthAuthorizationValue('scoped_teams', [orgTeams[0].id])
                    }
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
                const scopes = oauthAuthorizeLogic.values.scopes
                await oauthAuthorize(
                    {
                        ...values,
                        allow: true,
                        scopes,
                    },
                    () => actions.setAuthorizationComplete(true)
                )
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
        scopeDescriptions: [
            (s) => [s.scopes],
            (scopes: string[]): string[] => {
                const minimumEquivalentScopes = getMinimumEquivalentScopes(scopes)

                return minimumEquivalentScopes.map(getScopeDescription).filter(Boolean) as string[]
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

            actions.setScopesWereDefaulted(scopesWereDefaulted)
            actions.setIsMcpResource(isMcpResource)
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
