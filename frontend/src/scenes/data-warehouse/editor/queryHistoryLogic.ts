import { actions, kea, path, reducers } from 'kea'

import type { queryHistoryLogicType } from './queryHistoryLogicType'

export const queryHistoryLogic = kea<queryHistoryLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryHistoryLogic']),
    actions({
        openHistoryModal: true,
        closeHistoryModal: true,
    }),
    reducers({
        isHistoryModalOpen: [
            false as boolean,
            {
                openHistoryModal: () => true,
                closeHistoryModal: () => false,
            },
        ],
    }),
])
