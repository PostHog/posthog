import { actions, kea, path, reducers } from 'kea'

import type { addTilePickerModalLogicType } from './addTilePickerModalLogicType'

export type DashboardAddTileType = 'insight' | 'text_card' | 'button' | 'widget'

export const addTilePickerModalLogic = kea<addTilePickerModalLogicType>([
    path(['scenes', 'dashboard', 'addTilePickerModalLogic']),
    actions({
        showAddTilePickerModal: true,
        hideAddTilePickerModal: true,
    }),
    reducers({
        addTilePickerModalVisible: [
            false,
            {
                showAddTilePickerModal: () => true,
                hideAddTilePickerModal: () => false,
            },
        ],
    }),
])
