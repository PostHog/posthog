import { actions, actions, afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'

import { LinkType } from './linkConfigurationLogic'
import type { linksLogicType } from './linksLogicType'

export const linksLogic = kea<linksLogicType>([
    path(() => ['scenes', 'links', 'linksLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        deleteLink: (link: LinkType) => ({ link }),
    }),
    loaders(() => ({
        links: [
            [] as LinkType[],
            {
                loadLinks: async () => {
                    const response = await api.links.list()
                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        deleteLink: async ({ link }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/links`,
                object: { name: link.short_link_domain + '/' + link.short_code, id: link.id },
                callback: () => {
                    actions.loadLinks()
                },
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadLinks()
    }),
])
