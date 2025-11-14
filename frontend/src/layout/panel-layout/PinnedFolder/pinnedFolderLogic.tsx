import { actions, afterMount, kea, listeners, path, reducers } from 'kea'

import api from 'lib/api'

import { splitProtocolPath } from '~/layout/panel-layout/ProjectTree/utils'

import type { pinnedFolderLogicType } from './pinnedFolderLogicType'

export const pinnedFolderLogic = kea<pinnedFolderLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'pinnedFolderLogic']),
    actions({
        setPinnedFolder: (id: string) => ({ id }),
        loadPinnedFolder: true,
    }),
    reducers(() => ({
        pinnedFolder: [
            'loading://',
            {
                setPinnedFolder: (_, { id }) => id,
            },
        ],
    })),
    listeners(({ actions }) => ({
        setPinnedFolder: async ({ id }) => {
            const [protocol, path] = splitProtocolPath(id)
            await api.persistedFolder.create({ protocol, path, type: 'pinned' })
        },
        loadPinnedFolder: async () => {
            const folders = await api.persistedFolder.list()
            const pinned = folders.results.find((folder) => folder.type === 'pinned')
            const folderId = pinned ? `${pinned.protocol || 'products://'}${pinned.path}` : 'products://'
            actions.setPinnedFolder(folderId)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPinnedFolder()
    }),
])
