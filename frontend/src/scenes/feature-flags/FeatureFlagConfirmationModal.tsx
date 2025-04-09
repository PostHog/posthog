import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'lib/utils'

import { FeatureFlagType } from '~/types'

interface FeatureFlagConfirmationModalProps {
    isOpen: boolean
    featureFlag: FeatureFlagType
    activeNewValue?: boolean // Optional now as we support both toggle and save flows
    changes?: string[] // List of changes being made to the flag
    onConfirm: () => void
    onCancel: () => void
}

export function FeatureFlagConfirmationModal({
    isOpen,
    featureFlag,
    activeNewValue,
    changes = [],
    onConfirm,
    onCancel,
}: FeatureFlagConfirmationModalProps): JSX.Element {
    // Handle toggle mode (legacy behavior)
    const isToggleMode = activeNewValue !== undefined

    let title: string
    let description: JSX.Element

    if (isToggleMode) {
        const action = activeNewValue ? 'enable' : 'disable'
        const actionCapitalized = capitalizeFirstLetter(action)
        const actionEffect = activeNewValue ? 'activate' : 'deactivate'

        title = `${actionCapitalized} feature flag "${featureFlag.key}"?`
        description = (
            <>
                <p>
                    <span>
                        Are you sure you want to {action} this feature flag? This will {actionEffect} it for all users
                        within the release conditions.
                    </span>
                </p>
                <p>
                    <span>
                        Changes to feature flags can significantly impact your application. Please ensure you understand
                        the consequences of this change.
                    </span>
                </p>
            </>
        )
    } else {
        // Save mode with multiple changes
        title = `Confirm changes to feature flag "${featureFlag.key}"?`
        description = (
            <>
                <p>
                    <span>You are about to save the following changes:</span>
                </p>
                <ul className="ml-4 mt-2 list-disc">
                    {changes.map((change, index) => (
                        <li key={index}>
                            <span>{change}</span>
                        </li>
                    ))}
                </ul>
                <p className="mt-4">
                    <span>
                        These changes will immediately affect users matching the release conditions. Please ensure you
                        understand the consequences before proceeding.
                    </span>
                </p>
            </>
        )
    }

    return (
        <LemonModal
            isOpen={isOpen}
            title={<span>{title}</span>}
            description={description}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel}>
                        <span>Cancel</span>
                    </LemonButton>
                    <LemonButton type="primary" onClick={onConfirm}>
                        <span>
                            {isToggleMode
                                ? `${capitalizeFirstLetter(activeNewValue ? 'enable' : 'disable')} flag`
                                : 'Save changes'}
                        </span>
                    </LemonButton>
                </>
            }
            onClose={onCancel}
        />
    )
}
