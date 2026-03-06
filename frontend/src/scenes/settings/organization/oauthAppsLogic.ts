import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import type { oauthAppsLogicType } from './oauthAppsLogicType'

export const oauthAppsLogic = kea<oauthAppsLogicType>([
    path(['scenes', 'settings', 'organization', 'oauthAppsLogic']),

    loaders(() => ({
        oauthApps: [
            [] as OrganizationOAuthApplicationApi[],
            {
                loadOAuthApps: async () => {
                    const response = await api.organizationOAuthApplications.list()
                    return response.results
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadOAuthApps()
    }),
])
