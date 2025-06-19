import { actions, connect, kea, path, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import api from 'lib/api'
import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { projectTreeDataLogic } from '../ProjectTree/projectTreeDataLogic'
import type { pinnedFolderLogicType } from './pinnedFolderLogicType'

export const pinnedFolderLogic = kea<pinnedFolderLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'pinnedFolderLogic']),
    connect({
        actions: [
            projectTreeDataLogic,
            ['addShortcutItem'],
        ],
    }),
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
                    return 'shortcuts://'
                },
            },
        ],
    })),
    reducers(() => ({
        pinnedFolderSource: [
            'loading://',
            { persist: true, prefix: `${getCurrentTeamIdOrNone()}__${getCurrentUserIdOrNone()}__` },
            {
                setPinnedFolder: (_, { id }) => id,
            },
        ],
        selectedFolder: [
            'shortcuts://',
            {
                setSelectedFolder: (_, { id }) => id,
            },
        ],
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
                // setPinnedFolder: () => false,
                addShortcutItem: () => false,
            },
        ],
    })),
    // listeners(() => ({
    //     setPinnedFolder: async ({ id }) => {
    //         const [protocol, path] = splitProtocolPath(id)
    //         await api.persistedFolder.create({ protocol, path, type: 'pinned' })
    //     },
    // })),
    // afterMount(({ actions, values }) => {
    //     if (values.selectedFolder !== values.pinnedFolder) {
    //         actions.setSelectedFolder(values.pinnedFolder)
    //     }
    // }),
])
