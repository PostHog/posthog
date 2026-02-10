import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import type { connectedAccountsLogicType } from './connectedAccountsLogicType'

export interface SocialConnection {
    id: number
    provider: string
    uid: string
    created: string
}

export const connectedAccountsLogic = kea<connectedAccountsLogicType>([
    path(['scenes', 'settings', 'user', 'connectedAccountsLogic']),
    connect(() => ({
        values: [userLogic, ['user'], preflightLogic, ['preflight']],
    })),
    actions({
        unlinkConnection: (id: number) => ({ id }),
    }),
    loaders(({ values }) => ({
        connections: [
            [] as SocialConnection[],
            {
                loadConnections: async () => {
                    const response = await api.get('api/social/connections/')
                    return response.results ?? response
                },
                unlinkConnection: async ({ id }) => {
                    await api.delete(`api/social/connections/${id}/`)
                    lemonToast.success('Account unlinked successfully')
                    return values.connections.filter((c) => c.id !== id)
                },
            },
        ],
    })),
    selectors(() => ({
        availableProviders: [
            (s) => [s.preflight],
            (preflight): { key: string; name: string }[] => {
                if (!preflight?.available_social_auth_providers) {
                    return []
                }
                const providerNames: Record<string, string> = {
                    github: 'GitHub',
                    'google-oauth2': 'Google',
                    gitlab: 'GitLab',
                }
                return Object.entries(preflight.available_social_auth_providers)
                    .filter(([, enabled]) => enabled)
                    .map(([key]) => ({ key, name: providerNames[key] || key }))
            },
        ],
        canUnlink: [
            (s) => [s.connections, s.user],
            (connections, user): ((id: number) => boolean) => {
                return (id: number) => {
                    const hasPassword = user?.has_password ?? false
                    const remainingAfterRemoval = connections.filter((c) => c.id !== id).length
                    return hasPassword || remainingAfterRemoval > 0
                }
            },
        ],
    })),
    listeners(() => ({
        unlinkConnectionFailure: ({ error }) => {
            lemonToast.error(typeof error === 'string' ? error : 'Failed to unlink account')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadConnections()
    }),
])
