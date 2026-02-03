import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardLogic } from './dashboardLogic'

export function AddInsightToDashboardModalV2(): JSX.Element {
    const { hideAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)

    return (
        <LemonModal
            title="Add insight to dashboard"
            onClose={hideAddInsightToDashboardModal}
            isOpen={addInsightToDashboardModalVisible}
            footer={
                <>
                    <LemonButton type="secondary" data-attr="dashboard-cancel" onClick={hideAddInsightToDashboardModal}>
                        Cancel
                    </LemonButton>
                </>
            }
        >
            {/* TODO: Implement new modal content for V2 experiment */}
            <div className="p-4 text-center text-secondary">
                <p>Dashboard: {dashboard?.name}</p>
                <p>New modal content coming soon...</p>
            </div>
        </LemonModal>
    )
}
