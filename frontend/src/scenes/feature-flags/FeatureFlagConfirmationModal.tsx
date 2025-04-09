import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'lib/utils'

import { FeatureFlagType } from '~/types'

interface FeatureFlagConfirmationModalProps {
    isOpen: boolean
    featureFlag: FeatureFlagType
    activeNewValue: boolean
    onConfirm: () => void
    onCancel: () => void
}

export function FeatureFlagConfirmationModal({
    isOpen,
    featureFlag,
    activeNewValue,
    onConfirm,
    onCancel,
}: FeatureFlagConfirmationModalProps): JSX.Element {
    const action = activeNewValue ? 'enable' : 'disable'
    const actionCapitalized = capitalizeFirstLetter(action)
    const actionEffect = activeNewValue ? 'activate' : 'deactivate'

    return (
        <LemonModal
            isOpen={isOpen}
            title={
                <span>
                    <span>{actionCapitalized}</span>
                    <span> feature flag "</span>
                    <span>{featureFlag.key}</span>
                    <span>"?</span>
                </span>
            }
            description={
                <>
                    <p>
                        <span>
                            <span>Are you sure you want to </span>
                            <span>{action}</span>
                            <span> this feature flag? This will </span>
                            <span>{actionEffect}</span>
                            <span> it for all users within the release conditions.</span>
                        </span>
                    </p>
                    <p>
                        <span>
                            Changes to feature flags can significantly impact your application. Please ensure you
                            understand the consequences of this change.
                        </span>
                    </p>
                </>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel}>
                        <span>Cancel</span>
                    </LemonButton>
                    <LemonButton type="primary" onClick={onConfirm}>
                        <span>
                            <span>{actionCapitalized}</span>
                            <span> flag</span>
                        </span>
                    </LemonButton>
                </>
            }
            onClose={onCancel}
        />
    )
}
