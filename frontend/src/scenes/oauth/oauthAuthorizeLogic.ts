import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
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

export const oauthAuthorizeLogic = kea<oauthAuthorizeLogicType>([
    path(['oauth', 'authorize']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        setScopes: (scopes: string[]) => ({ scopes }),
        cancel: () => ({}),
    }),
    loaders({
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
    listeners({
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
    reducers({
        scopes: [
            [] as string[],
            {
                setScopes: (_, { scopes }) => scopes,
            },
        ],
    }),
    forms(() => ({
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
                const params = new URLSearchParams(location.search)

                const response = await api.create('/oauth/authorize/', {
                    client_id: params.get('client_id'),
                    redirect_uri: params.get('redirect_uri'),
                    response_type: params.get('response_type'),
                    state: params.get('state'),
                    scope: params.get('scope'),
                    code_challenge: params.get('code_challenge'),
                    code_challenge_method: params.get('code_challenge_method'),
                    nonce: params.get('nonce'),
                    claims: params.get('claims'),
                    scoped_organizations: values.access_type === 'organizations' ? values.scoped_organizations : [],
                    scoped_teams: values.access_type === 'teams' ? values.scoped_teams : [],
                    access_type: values.access_type,
                    allow: true,
                })

                if (response.redirect_to) {
                    location.href = response.redirect_to
                    return
                }
            },
        },
    })),
    selectors(() => ({
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
    })),
    urlToAction(({ actions }) => ({
        '/oauth/authorize': (_, searchParams) => {
            const scopes = searchParams['scope']?.split(' ') ?? DEFAULT_OAUTH_SCOPES
            actions.setScopes(scopes)
            actions.loadOAuthApplication()
            actions.loadAllTeams()
        },
    })),
])
