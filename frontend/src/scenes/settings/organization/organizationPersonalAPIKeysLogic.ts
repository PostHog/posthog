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
                    const response = await personalApiKeysList(ApiConfig.getCurrentOrganizationId())
                    return response.results
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadKeys()
    }),
])
