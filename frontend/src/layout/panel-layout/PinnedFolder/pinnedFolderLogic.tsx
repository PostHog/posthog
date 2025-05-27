import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import api from 'lib/api'
import { getCurrentTeamId, getCurrentUserId } from 'lib/utils/getAppContext'

import { splitProtocolPath } from '~/layout/panel-layout/ProjectTree/utils'

import type { pinnedFolderLogicType } from './pinnedFolderLogicType'

export const pinnedFolderLogic = kea<pinnedFolderLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'pinnedFolderLogic']),
    actions({
        showModal: true,
        hideModal: true,
        setPinnedFolder: (id: string) => ({ id }),
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
            },
        ],
    })),
    reducers(() => ({
        pinnedFolderSource: [
            'loading://',
            { persist: true, prefix: `${getCurrentTeamId()}__${getCurrentUserId()}__` },
            {
                setPinnedFolder: (_, { id }) => id,
            },
        ],
        selectedFolder: [
            'products://',
            {
                setSelectedFolder: (_, { id }) => id,
            },
        ],
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
                setPinnedFolder: () => false,
            },
        ],
    })),
    listeners(() => ({
        setPinnedFolder: async ({ id }) => {
            const [protocol, path] = splitProtocolPath(id)
            await api.persistedFolder.create({ protocol, path, type: 'pinned' })
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.selectedFolder !== values.pinnedFolder) {
            actions.setSelectedFolder(values.pinnedFolder)
        }
    }),
])
