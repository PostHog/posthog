import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { downgradeLogic } from './downgradeLogic'

export function DowngradeModal(): JSX.Element | null {
    const { isDowngradeModalOpen, currentAddon } = useValues(downgradeLogic)
    const { hideDowngradeModal, handleDowngrade } = useActions(downgradeLogic)

    if (!currentAddon) {
        return null
    }

    return (
        <LemonModal
            isOpen={isDowngradeModalOpen}
            onClose={hideDowngradeModal}
            title={`Unsubscribe from ${currentAddon.name}`}
            description="Your team is actively using these features and will lose access to it immediately"
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideDowngradeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" status="danger" onClick={handleDowngrade}>
                        Unsubscribe
                    </LemonButton>
                </>
            }
        >
            <div className="mt-2 mb-6">TODO: Add features that are used here</div>
        </LemonModal>
    )
}
