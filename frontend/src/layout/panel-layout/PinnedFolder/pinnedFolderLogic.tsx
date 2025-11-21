import { actions, afterMount, kea, path, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import { splitProtocolPath } from '~/layout/panel-layout/ProjectTree/utils'

import type { pinnedFolderLogicType } from './pinnedFolderLogicType'

export const pinnedFolderLogic = kea<pinnedFolderLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'pinnedFolderLogic']),
    actions({
        setSelectedFolder: (id: string) => ({ id }),
    }),
    lazyLoaders(() => ({
        pinnedFolder: [
            'loading://',
            {
                loadPinnedFolder: async () => {
                    const folders = await api.persistedFolder.list()
                    const pinned = folders.results.find((folder) => folder.type === 'pinned')
                    if (pinned) {
                        return `${pinned.protocol || 'products://'}${pinned.path}`
                    }
                    return 'products://'
                },
                setPinnedFolder: async (id: string) => {
                    const [protocol, path] = splitProtocolPath(id)
                    await api.persistedFolder.create({ protocol, path, type: 'pinned' })

                    return id
                },
            },
        ],
    })),
    reducers(() => ({
        selectedFolder: [
            'products://',
            {
                setSelectedFolder: (_, { id }) => id,
            },
        ],
    })),
    afterMount(({ actions, values }) => {
        if (values.selectedFolder !== values.pinnedFolder) {
            actions.setSelectedFolder(values.pinnedFolder)
        }
    }),
])
