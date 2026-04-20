import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { splitProtocolPath } from '~/layout/panel-layout/ProjectTree/utils'

import type { pinnedFolderLogicType } from './pinnedFolderLogicType'

const LOCAL_STORAGE_PINNED_FOLDER_KEY = 'layout.panel-layout.PinnedFolder.pinnedFolderLogic.lazyLoaders.pinnedFolder.v2'

export const pinnedFolderLogic = kea<pinnedFolderLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'pinnedFolderLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setSelectedFolder: (id: string) => ({ id }),
    }),
    reducers(() => ({
        selectedFolder: [
            'products://',
            {
                setSelectedFolder: (_, { id }) => id,
            },
        ],
    })),
    selectors({
        isCustomProductsSidebarEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR] === 'test',
        ],
    }),
    lazyLoaders(({ values }) => ({
        pinnedFolder: [
            localStorage.getItem(LOCAL_STORAGE_PINNED_FOLDER_KEY) || 'loading://',
            {
                loadPinnedFolder: async () => {
                    let pinnedFolder = values.isCustomProductsSidebarEnabled ? 'custom-products://' : 'products://'

                    // If we're testing the sidebar we don't need to query this, just use the custom products list
                    if (!values.isCustomProductsSidebarEnabled) {
                        const folders = await api.persistedFolder.list()
                        const pinned = folders.results.find((folder) => folder.type === 'pinned')

                        if (pinned) {
                            pinnedFolder = `${pinned.protocol || 'products://'}${pinned.path}`
                        }
                    }

                    localStorage.setItem(LOCAL_STORAGE_PINNED_FOLDER_KEY, pinnedFolder)
                    return pinnedFolder
                },
                setPinnedFolder: async (id: string) => {
                    const newPinnedFolder = values.isCustomProductsSidebarEnabled ? 'custom-products://' : id

                    if (!values.isCustomProductsSidebarEnabled) {
                        const [protocol, path] = splitProtocolPath(id)
                        await api.persistedFolder.create({ protocol, path, type: 'pinned' })
                    }

                    localStorage.setItem(LOCAL_STORAGE_PINNED_FOLDER_KEY, newPinnedFolder)
                    return newPinnedFolder
                },
            },
        ],
    })),
    afterMount(({ actions, values }) => {
        if (values.selectedFolder !== values.pinnedFolder) {
            actions.setSelectedFolder(values.pinnedFolder)
        }
    }),
])
