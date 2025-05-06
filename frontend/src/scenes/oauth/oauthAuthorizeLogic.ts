import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { DEFAULT_OAUTH_SCOPES, getMinimumEquivalentScopes, getScopeDescription } from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import type { OrganizationBasicType, TeamBasicType } from '~/types'

import type { oauthAuthorizeLogicType } from './oauthAuthorizeLogicType'

export type OAuthApplicationType = {
    name: string
}

export type OAuthAuthorizationFormValues = {
    scoped_organizations: number[]
    scoped_teams: number[]
    access_type: 'all' | 'organizations' | 'teams'
}

export const oauthAuthorizeLogic = kea<oauthAuthorizeLogicType>({
    path: ['oauth', 'authorize'],
    connect: () => ({
        values: [userLogic, ['user']],
    }),
    actions: () => ({
        setScopes: (scopes: string[]) => ({ scopes }),
        cancel: () => ({}),
    }),
    loaders: () => ({
        allTeams: [
            null as TeamBasicType[] | null,
            {
                loadAllTeams: async () => {
                    return await api.loadPaginatedResults('api/projects')
                },
            },
        ],
        oauthApplication: [
            null as OAuthApplicationType | null,
            {
                loadOAuthApplication: async () => {
                    return {
                        name: 'PostHog',
                    }
                },
            },
        ],
    }),
    listeners: () => ({
        cancel: () => {
            const params = new URLSearchParams(window.location.search)
            const redirectUri = params.get('redirect_uri')
            if (!redirectUri) {
                return router.actions.push('/')
            }

            const url = new URL(redirectUri)

            url.searchParams.set('error', 'access_denied')
            url.searchParams.set('error_description', 'User denied request')

            // Preserve state if present
            const state = params.get('state')
            if (state) {
                url.searchParams.set('state', state)
            }

            location.replace(url.toString())
        },
    }),
    reducers: () => ({
        scopes: [
            [] as string[],
            {
                setScopes: (_, { scopes }) => scopes,
            },
        ],
    }),
    forms: () => ({
        oauthAuthorization: {
            defaults: {
                scoped_organizations: [],
                scoped_teams: [],
                access_type: 'all',
            } as OAuthAuthorizationFormValues,
            errors: ({ access_type, scoped_organizations, scoped_teams }) => ({
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
            submit: async () => {
                const params = new URLSearchParams(location.search)
                const expectedKeys = [
                    'client_id',
                    'redirect_uri',
                    'response_type',
                    'state',
                    'scope',
                    'code_challenge',
                    'code_challenge_method',
                    'nonce',
                    'claims',
                ]

                const formData = new FormData()
                for (const key of expectedKeys) {
                    const value = params.get(key)
                    if (value) {
                        formData.append(key, value)
                    }
                }
                formData.append('allow', 'Authorize')

                const response = await fetch('/oauth/authorize/', {
                    method: 'POST',
                    body: formData,
                    credentials: 'include',
                })

                if (response.redirected) {
                    location.href = response.url
                    return
                }
            },
        },
    }),
    selectors: () => ({
        allOrganizations: [
            (s) => [s.user],
            (user): OrganizationBasicType[] => {
                return user?.organizations ?? []
            },
        ],
        scopeDescriptions: [
            (s) => [s.scopes],
            (scopes): string[] => {
                const minimumEquivalentScopes = getMinimumEquivalentScopes(scopes)

                return minimumEquivalentScopes.map(getScopeDescription)
            },
        ],
    }),
    urlToAction: ({ actions }) => ({
        '/oauth/authorize': (_, searchParams) => {
            const scopes = searchParams['scope']?.split(' ') ?? DEFAULT_OAUTH_SCOPES
            actions.setScopes(scopes)
            actions.loadOAuthApplication()
            actions.loadAllTeams()
        },
    }),
})
