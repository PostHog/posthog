import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { teamsDowngradeLogic } from './teamsDowngradeLogic'

export function TeamsDowngradeModal(): JSX.Element {
    const { isTeamsDowngradeModalOpen, enforce2FA } = useValues(teamsDowngradeLogic)
    const { hideTeamsDowngradeModal, handleTeamsDowngrade } = useActions(teamsDowngradeLogic)

    return (
        <LemonModal
            title="Unsubscribe from Teams"
            description="Your team is currently using the following features and will lose access to them if you unsubscribe:"
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
            <div className="space-y-2">
                <p>TODO: Add features that are currently being used</p>
                {enforce2FA && (
                    <div className="flex items-center gap-2">
                        <IconWarning className="text-warning" />
                        <span>Enforced 2FA</span>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
