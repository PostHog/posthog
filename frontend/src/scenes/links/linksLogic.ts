import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { linkConfigurationLogicType } from './linksLogicType'
import { LinkType } from './linkConfigurationLogic'

export const linksLogic = kea<linkConfigurationLogicType>([
    path(() => ['scenes', 'links', 'linksLogic']),
    loaders(() => ({
        links: [
            [] as LinkType[],
            {
                loadLinks: async () => {
                    const response = await api.get('api/links')
                    return response.results
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadLinks()
    }),
])
