import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiConfig } from 'lib/api'

import { getPersonalApiKeysListUrl } from 'products/platform_features/frontend/generated/api'
import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import type { organizationPersonalAPIKeysLogicType } from './organizationPersonalAPIKeysLogicType'

export const organizationPersonalAPIKeysLogic = kea<organizationPersonalAPIKeysLogicType>([
    path(['scenes', 'settings', 'organization', 'organizationPersonalAPIKeysLogic']),
    loaders({
        keys: [
            [] as OrganizationPersonalAPIKeyApi[],
            {
                loadKeys: async () => {
                    // Page through everything — an incomplete list would be a security-audit blind spot.
                    const url = getPersonalApiKeysListUrl(ApiConfig.getCurrentOrganizationId())
                    return await api.loadPaginatedResults<OrganizationPersonalAPIKeyApi>(url)
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadKeys()
    }),
])
