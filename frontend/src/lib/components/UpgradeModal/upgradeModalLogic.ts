import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import type { upgradeModalLogicType } from './upgradeModalLogicType'

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
        guardAvailableFeature: (
            featureKey: AvailableFeature,
            featureAvailableCallback?: () => void,
            guardOn: {
                cloud: boolean
                selfHosted: boolean
            } = {
                cloud: true,
                selfHosted: true,
            },
            // how much of the feature has been used (eg. number of recording playlists created),
            // which will be compared to the limit for their subscriptions
            currentUsage?: number,
            isGrandfathered?: boolean
        ) => ({ featureKey, featureAvailableCallback, guardOn, currentUsage, isGrandfathered }),
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
    selectors({
        // sceneConfig: [
        //     (s) => [s.scene],
        //     (scene: Scene): SceneConfig | null => {
        //         return sceneConfigurations[scene] || null
        //     },
        // ],
    }),
    listeners(({ actions }) => ({
        showUpgradeModal: ({ featureKey }) => {
            eventUsageLogic.actions.reportUpgradeModalShown(featureKey)
        },
        guardAvailableFeature: ({ featureKey, featureAvailableCallback, guardOn, currentUsage, isGrandfathered }) => {
            const { preflight } = preflightLogic.values
            let featureAvailable: boolean
            if (!preflight) {
                featureAvailable = false
            } else if (!guardOn.cloud && preflight.cloud) {
                featureAvailable = true
            } else if (!guardOn.selfHosted && !preflight.cloud) {
                featureAvailable = true
            } else {
                featureAvailable = userLogic.values.hasAvailableFeature(featureKey, currentUsage)
            }
            if (featureAvailable) {
                featureAvailableCallback?.()
            } else {
                actions.showUpgradeModal(featureKey, currentUsage, isGrandfathered)
            }
        },
    })),
])
