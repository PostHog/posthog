import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import type { upgradeModalLogicType } from './upgradeModalLogicType'

export type GuardAvailableFeatureFn = (
    featureKey?: AvailableFeature,
    featureAvailableCallback?: () => void,
    options?: {
        guardOnCloud?: boolean
        guardOnSelfHosted?: boolean
        currentUsage?: number
        isGrandfathered?: boolean
    }
) => boolean

export const upgradeModalLogic = kea<upgradeModalLogicType>([
    path(['lib', 'components', 'UpgradeModal', 'upgradeModalLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags'], userLogic, ['hasAvailableFeature']],
    })),
    actions({
        showUpgradeModal: (featureKey: AvailableFeature, currentUsage?: number, isGrandfathered?: boolean) => ({
            featureKey,
            currentUsage,
            isGrandfathered,
        }),
        hideUpgradeModal: true,
    }),
    reducers({
        upgradeModalFeatureKey: [
            null as AvailableFeature | null,
            {
                showUpgradeModal: (_, { featureKey }) => featureKey,
                hideUpgradeModal: () => null,
            },
        ],
        upgradeModalFeatureUsage: [
            null as number | null,
            {
                showUpgradeModal: (_, { currentUsage }) => currentUsage ?? null,
                hideUpgradeModal: () => null,
            },
        ],
        upgradeModalIsGrandfathered: [
            null as boolean | null,
            {
                showUpgradeModal: (_, { isGrandfathered }) => isGrandfathered ?? null,
                hideUpgradeModal: () => null,
            },
        ],
    }),
    selectors(() => ({
        guardAvailableFeature: [
            (s) => [s.preflight, s.hasAvailableFeature],
            (): GuardAvailableFeatureFn => {
                return (featureKey, featureAvailableCallback): boolean => {
                    if (!featureKey) {
                        featureAvailableCallback?.()
                        return true
                    }
                    featureAvailableCallback?.()

                    return true
                }
            },
        ],
    })),
    listeners(() => ({
        showUpgradeModal: ({ featureKey }) => {
            eventUsageLogic.actions.reportUpgradeModalShown(featureKey)
        },
    })),
])
