import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'

import { personalApiKeysList } from 'products/platform_features/frontend/generated/api'
import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import type { organizationPersonalAPIKeysLogicType } from './organizationPersonalAPIKeysLogicType'

export const organizationPersonalAPIKeysLogic = kea<organizationPersonalAPIKeysLogicType>([
    path(['scenes', 'settings', 'organization', 'organizationPersonalAPIKeysLogic']),
    loaders({
        keys: [
            [] as OrganizationPersonalAPIKeyApi[],
            {
                loadKeys: async () => {
                    const organizationId = ApiConfig.getCurrentOrganizationId()
                    // Page through everything — an incomplete list would be a security-audit blind spot.
                    const limit = 100
                    const allKeys: OrganizationPersonalAPIKeyApi[] = []
                    for (let offset = 0; ; offset += limit) {
                        const response = await personalApiKeysList(organizationId, { limit, offset })
                        allKeys.push(...response.results)
                        if (!response.next) {
                            return allKeys
                        }
                    }
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadKeys()
    }),
])
