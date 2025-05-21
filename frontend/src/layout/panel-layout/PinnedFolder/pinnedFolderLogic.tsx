import { actions, afterMount, kea, path, reducers } from 'kea'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

export const pinnedFolderLogic = kea([
    path(['layout', 'panel-layout', 'PinnedFolder', 'pinnedFolderLogic']),
    actions({
        showModal: true,
        hideModal: true,
        setPinnedFolder: (id: string) => ({ id }),
        setSelectedFolder: (id: string) => ({ id }),
    }),
    reducers(() => ({
        pinnedFolder: [
            'products://',
            { persist: true, prefix: `${getCurrentTeamId()}__` },
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
    afterMount(({ actions, values }) => {
        if (values.selectedFolder !== values.pinnedFolder) {
            actions.setSelectedFolder(values.pinnedFolder)
        }
    }),
])
