import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { DEFAULT_OAUTH_SCOPES, getMinimumEquivalentScopes, getScopeDescription } from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import type { OAuthApplicationPublicMetadata, OrganizationBasicType, TeamBasicType, UserType } from '~/types'

import type { oauthAuthorizeLogicType } from './oauthAuthorizeLogicType'

export type OAuthAuthorizationFormValues = {
    scoped_organizations: number[]
    scoped_teams: number[]
    access_type: 'all' | 'organizations' | 'teams'
}

const oauthAuthorize = async (values: OAuthAuthorizationFormValues & { allow: boolean }): Promise<void> => {
    try {
        const response = await api.create('/oauth/authorize/', {
            client_id: router.values.searchParams['client_id'],
            redirect_uri: router.values.searchParams['redirect_uri'],
            response_type: router.values.searchParams['response_type'],
            state: router.values.searchParams['state'],
            scope: router.values.searchParams['scope'],
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
            location.href = response.redirect_to
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
    listeners(({ values }) => ({
        cancel: async () => {
            await oauthAuthorize({
                scoped_organizations: values.oauthAuthorization.scoped_organizations,
                scoped_teams: values.oauthAuthorization.scoped_teams,
                access_type: values.oauthAuthorization.access_type,
                allow: false,
            })
        },
    })),
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
                await oauthAuthorize({
                    ...values,
                    allow: true,
                })
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
        scopeDescriptions: [
            (s) => [s.scopes],
            (scopes: string[]): string[] => {
                const minimumEquivalentScopes = getMinimumEquivalentScopes(scopes)

                return minimumEquivalentScopes.map(getScopeDescription)
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
    urlToAction(({ actions }) => ({
        '/oauth/authorize': (_, searchParams) => {
            const requestedScopes = searchParams['scope']?.split(' ')?.filter((scope: string) => scope.length) ?? []
            const scopes = requestedScopes.length === 0 ? DEFAULT_OAUTH_SCOPES : requestedScopes

            actions.setScopes(scopes)
            actions.loadOAuthApplication()
            actions.loadAllTeams()
        },
    })),
])
