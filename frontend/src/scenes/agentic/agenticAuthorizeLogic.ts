import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getMinimumEquivalentScopes, getScopeDescription } from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import type { OrganizationBasicType, TeamBasicType, UserType } from '~/types'

import type { agenticAuthorizeLogicType } from './agenticAuthorizeLogicType'

export type AgenticAuthorizationFormValues = {
    scoped_organizations: string[]
    scoped_teams: number[]
    access_type: 'teams'
}

export const agenticAuthorizeLogic = kea<agenticAuthorizeLogicType>([
    path(['agentic', 'authorize']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        setState: (state: string) => ({ state }),
        cancel: true,
    }),
    loaders(({ values }) => ({
        allTeams: [
            null as TeamBasicType[] | null,
            {
                loadAllTeams: async () => {
                    return await api.loadPaginatedResults('api/projects')
                },
            },
        ],
        pendingAuth: [
            null as { partner_name: string; scopes: string[] } | null,
            {
                loadPendingAuth: async () => {
                    return await api.get(`api/agentic/authorize/pending/?state=${encodeURIComponent(values.state)}`)
                },
            },
        ],
    })),
    reducers({
        state: [
            '' as string,
            {
                setState: (_, { state }) => state,
            },
        ],
    }),
    forms(({ values }) => ({
        agenticAuthorization: {
            defaults: {
                scoped_organizations: [],
                scoped_teams: [],
                access_type: 'teams',
            } as AgenticAuthorizationFormValues,
            errors: ({ scoped_organizations, scoped_teams }: AgenticAuthorizationFormValues) => ({
                scoped_organizations: !scoped_organizations?.length ? ('Select an organization' as any) : undefined,
                scoped_teams: !scoped_teams?.length ? ('Select a project' as any) : undefined,
            }),
            submit: async (formValues: AgenticAuthorizationFormValues) => {
                try {
                    const response = await api.create('api/agentic/authorize/confirm/', {
                        state: values.state,
                        team_id: formValues.scoped_teams[0],
                    })

                    if (response.redirect_url) {
                        window.location.href = response.redirect_url
                    }
                } catch (error: any) {
                    lemonToast.error('Something went wrong while authorizing')
                    throw error
                }
            },
        },
    })),
    listeners(() => ({
        cancel: () => {
            window.location.href = '/'
        },
    })),
    selectors(() => ({
        allOrganizations: [
            (s) => [s.user],
            (user: UserType): OrganizationBasicType[] => {
                return user?.organizations ?? []
            },
        ],
        filteredTeams: [
            (s) => [s.allTeams, s.agenticAuthorization],
            (allTeams: TeamBasicType[] | null, form: AgenticAuthorizationFormValues): TeamBasicType[] => {
                if (!allTeams) {
                    return []
                }
                const selectedOrgId = form.scoped_organizations[0]
                if (!selectedOrgId) {
                    return []
                }
                return allTeams.filter((team) => String(team.organization) === String(selectedOrgId) && !team.is_demo)
            },
        ],
        partnerName: [
            (s) => [s.pendingAuth],
            (pendingAuth: { partner_name: string; scopes: string[] } | null): string => {
                return pendingAuth?.partner_name ?? 'the requesting app'
            },
        ],
        scopes: [
            (s) => [s.pendingAuth],
            (pendingAuth: { partner_name: string; scopes: string[] } | null): string[] => {
                return pendingAuth?.scopes ?? []
            },
        ],
        scopeDescriptions: [
            (s) => [s.scopes],
            (scopes: string[]): string[] => {
                const minimumEquivalentScopes = getMinimumEquivalentScopes(scopes)
                return minimumEquivalentScopes.map(getScopeDescription).filter(Boolean) as string[]
            },
        ],
    })),
    urlToAction(({ actions }) => {
        const handleAuthorize = (_: Record<string, any>, searchParams: Record<string, any>): void => {
            if (searchParams['code']) {
                return
            }
            const state = (searchParams['state'] as string) ?? ''

            actions.setState(state)
            if (state) {
                actions.loadPendingAuth()
            }
            actions.loadAllTeams()
        }

        return {
            '/agentic/authorize': handleAuthorize,
            '/agentic/authorize/': handleAuthorize,
        }
    }),
])
