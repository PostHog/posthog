import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { FeatureFlagType } from '~/types'

interface FeatureFlagRolloutConfirmationModalProps {
    isOpen: boolean
    featureFlag: FeatureFlagType
    onConfirm: () => void
    onCancel: () => void
}

export function FeatureFlagRolloutConfirmationModal({
    isOpen,
    featureFlag,
    onConfirm,
    onCancel,
}: FeatureFlagRolloutConfirmationModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            title={`Update rollout conditions for "${featureFlag.key}"?`}
            description={
                <>
                    <p>
                        Are you sure you want to update the rollout conditions for this feature flag? This will change
                        which users the flag is enabled for.
                    </p>
                    <p>
                        Changes to rollout conditions can significantly impact your application's behavior. Please
                        ensure you understand the consequences of this change.
                    </p>
                </>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={onConfirm}>
                        Update conditions
                    </LemonButton>
                </>
            }
            onClose={onCancel}
        />
    )
}
