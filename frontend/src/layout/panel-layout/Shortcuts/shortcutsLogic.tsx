import { actions, kea, path, reducers } from 'kea'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import type { shortcutsLogicType } from './shortcutsLogicType'

export const shortcutsLogic = kea<shortcutsLogicType>([
    path(['layout', 'panel-layout', 'Shortcuts', 'shortcutsLogic']),

    actions({
        showModal: true,
        hideModal: true,
        setSelectedItem: (item: TreeDataItem | null) => ({ item }),
        addShortcutItem: (item: TreeDataItem) => ({ item }),
        deleteShortcut: (item: TreeDataItem) => ({ item }),
    }),
    reducers({
        shortcuts: [
            [] as TreeDataItem[],
            {
                addShortcutItem: (state, { item }) => [...state, item],
                deleteShortcut: (state, { item }) => state.filter((s) => s !== item),
            },
        ],
        selectedItem: [
            null as TreeDataItem | null,
            {
                setSelectedItem: (_, { item }) => item,
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
])
