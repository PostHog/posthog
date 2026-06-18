import { actions, events, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { connectedAppsLogicType } from './connectedAppsLogicType'

export interface ConnectedApp {
    id: string
    name: string
    logo_uri: string | null
    scopes: string[]
    authorized_at: string
    is_verified: boolean
    is_first_party: boolean
}

export const connectedAppsLogic = kea<connectedAppsLogicType>([
    path(['scenes', 'settings', 'user', 'connectedAppsLogic']),

    actions({
        revokeApp: (id: string) => ({ id }),
    }),

    loaders(({ values }) => ({
        connectedApps: [
            [] as ConnectedApp[],
            {
                loadConnectedApps: async () => {
                    return await api.get('api/oauth/connected-apps/')
                },
                revokeApp: async ({ id }) => {
                    await api.create(`api/oauth/connected-apps/${id}/revoke/`)
                    lemonToast.success('App access revoked')
                    return values.connectedApps.filter((app) => app.id !== id)
                },
            },
        ],
    })),

    events(({ actions }) => ({
        afterMount: () => actions.loadConnectedApps(),
    })),
])
