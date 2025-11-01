import { LemonDialog } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { FeatureFlagType } from '~/types'

type ConfirmationModalType = 'flag-status' | 'rollout' | 'multi-changes'

interface ConfirmationModalProps {
    featureFlag: FeatureFlagType
    type: ConfirmationModalType
    activeNewValue?: boolean // Only for flag-status type
    changes?: string[] // Only for multi-changes type
    customMessages?: string[] // Custom message(s) for multi-changes type
    onConfirm: () => void
}

/**
 * Opens a confirmation dialog for feature flag changes.
 * This is used for confirming status changes, rollout changes, or multiple changes at once.
 */
export function openConfirmationModal({
    featureFlag,
    type,
    activeNewValue,
    changes = [],
    customMessages,
    onConfirm,
}: ConfirmationModalProps): void {
    let title: string
    let description: JSX.Element

    switch (type) {
        case 'flag-status': {
            const action = activeNewValue ? 'enable' : 'disable'
            const actionCapitalized = capitalizeFirstLetter(action)
            const actionEffect = activeNewValue ? 'activate' : 'deactivate'

            title = `${actionCapitalized} feature flag "${featureFlag.key}"?`
            description = (
                <>
                    <p>
                        Are you sure you want to {action} this feature flag? This will {actionEffect} it for all users
                        within the release conditions.
                    </p>
                    <p>
                        Changes to feature flags can significantly impact your application. Please ensure you understand
                        the consequences of this change.
                    </p>
                </>
            )
            break
        }
        case 'rollout': {
            title = `Update rollout conditions for "${featureFlag.key}"?`
            description = (
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
            )
            break
        }
        case 'multi-changes': {
            title = `Confirm changes to feature flag "${featureFlag.key}"?`
            const defaultMessage =
                '⚠️ These changes will immediately affect users matching the release conditions. Please ensure you understand the consequences before proceeding.'

            const messagesToDisplay = customMessages && customMessages.length > 0 ? customMessages : [defaultMessage]

            description = (
                <>
                    <p>You are about to save the following changes:</p>
                    <ul className="ml-4 mt-2 list-disc">
                        {changes.map((change, index) => (
                            <li key={index}>{change}</li>
                        ))}
                    </ul>
                    {messagesToDisplay.map((message, index) => (
                        <p key={index} className="mt-4">
                            {message}
                        </p>
                    ))}
                </>
            )
            break
        }
    }

    LemonDialog.open({
        title,
        description,
        primaryButton: {
            children:
                type === 'flag-status'
                    ? `${capitalizeFirstLetter(activeNewValue ? 'enable' : 'disable')} flag`
                    : type === 'rollout'
                      ? 'Update conditions'
                      : 'Save changes',
            onClick: onConfirm,
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}
