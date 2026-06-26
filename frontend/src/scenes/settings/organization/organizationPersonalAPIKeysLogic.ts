import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiConfig } from 'lib/api'
import { fullName } from 'lib/utils/strings'

import { getPersonalApiKeysListUrl } from 'products/platform_features/frontend/generated/api'
import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import type { organizationPersonalAPIKeysLogicType } from './organizationPersonalAPIKeysLogicType'

export const organizationPersonalAPIKeysLogic = kea<organizationPersonalAPIKeysLogicType>([
    path(['scenes', 'settings', 'organization', 'organizationPersonalAPIKeysLogic']),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
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
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),
    selectors({
        // Client-side filtering — the full list is already loaded, so this stays in the browser.
        filteredKeys: [
            (s) => [s.keys, s.search],
            (keys, search): OrganizationPersonalAPIKeyApi[] => {
                const term = search.trim().toLowerCase()
                if (!term) {
                    return keys
                }
                return keys.filter((key) =>
                    [fullName(key.owner), key.owner.email, ...key.scopes].some((field) =>
                        field.toLowerCase().includes(term)
                    )
                )
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadKeys()
    }),
])
