import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { FeatureFlagType } from '~/types'

import { openConfirmationModal } from './ConfirmationModal'
import type { featureFlagConfirmationLogicType } from './featureFlagConfirmationLogicType'

/**
 * Detects feature flag changes that warrant confirmation.
 *
 * Detects the following types of changes:
 * - Active status (enabled/disabled)
 * - Rollout percentage changes
 * - Variant changes (adding/removing/modifying variants)
 * - Release condition changes (properties, targeting)
 * - Payload changes
 * - Other filter configuration changes
 *
 * Note: Some changes like name, description, and tags do NOT trigger confirmation
 * as they don't directly impact user experience.
 */
function detectFeatureFlagChanges(
    originalFlag: FeatureFlagType | null,
    updatedFlag: Partial<FeatureFlagType>
): string[] {
    const changes: string[] = []

    // Don't require confirmation for new flags
    if (!originalFlag || !updatedFlag.id) {
        return changes
    }

    // Check for active status changes
    if (originalFlag.active !== updatedFlag.active) {
        if (updatedFlag.active) {
            changes.push('Enable the feature flag')
        } else {
            changes.push('Disable the feature flag')
        }
    }

    // Check for any filter changes (comprehensive detection)
    const originalFilters = JSON.stringify(originalFlag.filters || {})
    const updatedFilters = JSON.stringify(updatedFlag.filters || {})

    if (originalFilters !== updatedFilters) {
        // Try to detect specific types of changes for better messaging
        const originalGroups = originalFlag.filters?.groups || []
        const updatedGroups = updatedFlag.filters?.groups || []

        // Check for rollout percentage changes
        const rolloutChanged = originalGroups.some((group, index) => {
            const updatedGroup = updatedGroups[index]
            return updatedGroup && group.rollout_percentage !== updatedGroup.rollout_percentage
        })

        // Check for variant changes
        const originalVariants = originalFlag.filters?.multivariate?.variants || []
        const updatedVariants = updatedFlag.filters?.multivariate?.variants || []
        const variantsChanged = JSON.stringify(originalVariants) !== JSON.stringify(updatedVariants)

        // Check for release condition changes (properties, etc.)
        const conditionsChanged = originalGroups.some((group, index) => {
            const updatedGroup = updatedGroups[index]
            return (
                updatedGroup && JSON.stringify(group.properties || []) !== JSON.stringify(updatedGroup.properties || [])
            )
        })

        // Check for payload changes
        const originalPayloads = originalFlag.filters?.payloads || {}
        const updatedPayloads = updatedFlag.filters?.payloads || {}
        const payloadsChanged = JSON.stringify(originalPayloads) !== JSON.stringify(updatedPayloads)

        // Add specific change messages
        if (rolloutChanged) {
            changes.push('Release condition rollout percentage changed')
        }
        if (variantsChanged) {
            if (updatedVariants.length > originalVariants.length) {
                changes.push('Variants added to feature flag')
            } else if (updatedVariants.length < originalVariants.length) {
                changes.push('Variants removed from feature flag')
            } else {
                changes.push('Variant configurations changed')
            }
        }
        if (conditionsChanged) {
            changes.push('Release conditions changed')
        }
        if (payloadsChanged) {
            changes.push('Payloads changed')
        }

        // If we haven't caught the specific change, add a generic message
        if (!rolloutChanged && !variantsChanged && !conditionsChanged && !payloadsChanged) {
            changes.push('Feature flag configuration changed')
        }
    }

    return changes
}

// Utility function for checking if confirmation is needed and showing modal
export function checkFeatureFlagConfirmation(
    originalFlag: FeatureFlagType | null,
    updatedFlag: FeatureFlagType,
    confirmationEnabled: boolean,
    customMessages: string[] | undefined,
    onConfirm: () => void
): boolean {
    // Check if confirmation is needed
    const needsConfirmation = !!updatedFlag.id && confirmationEnabled

    if (needsConfirmation) {
        const changes = detectFeatureFlagChanges(originalFlag, updatedFlag)

        if (changes.length > 0) {
            // Show confirmation modal
            openConfirmationModal({
                featureFlag: updatedFlag,
                type: 'multi-changes',
                changes: changes,
                customMessages: customMessages,
                onConfirm: onConfirm,
            })
            return true // Confirmation modal shown, don't proceed with save
        }
    }

    return false // No confirmation needed, proceed with save
}

export interface FeatureFlagConfirmationLogicProps {
    featureFlag: FeatureFlagType
    onConfirm: () => void
}

export const featureFlagConfirmationLogic = kea<featureFlagConfirmationLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagConfirmationLogic']),
    props({} as FeatureFlagConfirmationLogicProps),
    key(({ featureFlag }) => featureFlag.id ?? 'new'),
    actions({
        setFlagChanges: (changes: string[]) => ({ changes }),
        showConfirmationModal: (show: boolean) => ({ show }),
        confirmChanges: true,
    }),
    reducers({
        flagChanges: [
            [] as string[],
            {
                setFlagChanges: (_, { changes }: { changes: string[] }) => changes,
            },
        ],
        showSaveConfirmModal: [
            false,
            {
                showConfirmationModal: (_, { show }: { show: boolean }) => show,
            },
        ],
    }),
    selectors({
        hasChanges: [(s) => [s.flagChanges], (changes: string[]) => changes.length > 0],
    }),
    listeners(({ values, props }) => ({
        confirmChanges: () => {
            if (values.hasChanges) {
                openConfirmationModal({
                    featureFlag: props.featureFlag,
                    type: 'multi-changes',
                    changes: values.flagChanges,
                    onConfirm: props.onConfirm,
                })
            } else {
                props.onConfirm()
            }
        },
    })),
])

// Export the function for reuse in tests
export { detectFeatureFlagChanges }
