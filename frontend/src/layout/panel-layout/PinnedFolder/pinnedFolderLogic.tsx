import { actions, afterMount, connect, kea, path, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { splitProtocolPath } from '~/layout/panel-layout/ProjectTree/utils'

import type { pinnedFolderLogicType } from './pinnedFolderLogicType'

const LOCAL_STORAGE_PINNED_FOLDER_KEY = 'layout.panel-layout.PinnedFolder.pinnedFolderLogic.lazyLoaders.pinnedFolder'

export const pinnedFolderLogic = kea<pinnedFolderLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'pinnedFolderLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setSelectedFolder: (id: string) => ({ id }),
    }),
    lazyLoaders(({ values }) => ({
        pinnedFolder: [
            localStorage.getItem(LOCAL_STORAGE_PINNED_FOLDER_KEY) || 'loading://',
            {
                loadPinnedFolder: async () => {
                    const folders = await api.persistedFolder.list()
                    const pinned = folders.results.find((folder) => folder.type === 'pinned')

                    let pinnedFolder =
                        values.featureFlags[FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR] === 'test'
                            ? 'custom-products://'
                            : 'products://'
                    if (pinned) {
                        pinnedFolder = `${pinned.protocol || 'products://'}${pinned.path}`
                    }

                    localStorage.setItem(LOCAL_STORAGE_PINNED_FOLDER_KEY, pinnedFolder)
                    return pinnedFolder
                },
                setPinnedFolder: async (id: string) => {
                    const [protocol, path] = splitProtocolPath(id)
                    await api.persistedFolder.create({ protocol, path, type: 'pinned' })

                    localStorage.setItem(LOCAL_STORAGE_PINNED_FOLDER_KEY, id)
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
