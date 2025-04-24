import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'

import { ActivityScope } from '~/types'

import { multitabEditorLogic } from './multitabEditorLogic'
import { queryHistoryLogic } from './queryHistoryLogic'

export function QueryHistoryModal(): JSX.Element {
    const { isHistoryModalOpen } = useValues(queryHistoryLogic)
    const { closeHistoryModal } = useActions(queryHistoryLogic)
    const { editingView } = useValues(multitabEditorLogic)

    return (
        <LemonModal title="Query History" isOpen={isHistoryModalOpen} onClose={closeHistoryModal} width={800}>
            <ActivityLog
                scope={ActivityScope.DATA_WAREHOUSE_SAVED_QUERY}
                id={editingView?.id}
                caption="History of view changes"
            />
        </LemonModal>
    )
}
