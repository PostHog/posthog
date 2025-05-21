import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import type { shortcutsLogicType } from './shortcutsLogicType'

export const shortcutsLogic = kea<shortcutsLogicType>([
    path(['layout', 'panel-layout', 'Shortcuts', 'shortcutsLogic']),
    connect(() => ({
        values: [projectTreeDataLogic, ['shortcutData', 'shortcutDataLoading']],
        actions: [projectTreeDataLogic, ['loadShortcuts', 'addShortcutItem', 'deleteShortcut']],
    })),
    actions({
        showModal: true,
        hideModal: true,
        setSelectedItem: (id: TreeDataItem['id']) => ({ id }),
    }),

    reducers({
        selectedItemId: [
            null as TreeDataItem['id'] | null,
            {
                setSelectedItem: (_, { id }) => id,
            },
        ],
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
                addShortcutItem: () => false,
            },
        ],
    }),
    selectors({
        selectedItem: [
            (s) => [s.selectedItemId, s.shortcutData],
            (selectedItemId, shortcutData) =>
                selectedItemId ? shortcutData.find((item) => item.id === selectedItemId) : null,
        ],
        shortcutsLoading: [(s) => [s.shortcutDataLoading], (loading) => loading],
    }),
    afterMount(({ actions }) => {
        actions.loadShortcuts()
    }),
])
