import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { teamsDowngradeLogic } from './teamsDowngradeLogic'

export function TeamsDowngradeModal(): JSX.Element {
    const { isTeamsDowngradeModalOpen } = useValues(teamsDowngradeLogic)
    const { hideTeamsDowngradeModal, handleTeamsDowngrade } = useActions(teamsDowngradeLogic)

    return (
        <LemonModal
            title="Unsubscribe from Teams"
            description="You are about to lose access to the following features:"
            isOpen={isTeamsDowngradeModalOpen}
            onClose={hideTeamsDowngradeModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideTeamsDowngradeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" status="danger" onClick={handleTeamsDowngrade}>
                        Continue Unsubscribing
                    </LemonButton>
                </>
            }
        >
            <p>TODO: Add features that are currently being used</p>
        </LemonModal>
    )
}
