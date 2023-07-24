import { actions, kea, reducers, path, selectors, connect, listeners } from 'kea'
import { EarlyAccessFeature, posthog } from 'posthog-js'
import { loaders } from 'kea-loaders'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import type { featurePreviewsLogicType } from './featurePreviewsLogicType'

/** Features that can only be toggled if you fall under the `${flagKey}-preview` flag */
export const CONSTRAINED_PREVIEWS: Set<FeatureFlagKey> = new Set([FEATURE_FLAGS.POSTHOG_3000])

export interface EnrichedEarlyAccessFeature extends Omit<EarlyAccessFeature, 'flagKey'> {
    flagKey: string
    enabled: boolean
}

export const featurePreviewsLogic = kea<featurePreviewsLogicType>([
    path(['layout', 'navigation', 'TopBar', 'FeaturePreviewsModal']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['user']],
        asyncActions: [supportLogic, ['submitZendeskTicket']],
    }),
    actions({
        showFeaturePreviewsModal: true,
        hideFeaturePreviewsModal: true,
        updateEarlyAccessFeatureEnrollment: (flagKey: string, enabled: boolean) => ({ flagKey, enabled }),
        beginEarlyAccessFeatureFeedback: (flagKey: string) => ({ flagKey }),
        cancelEarlyAccessFeatureFeedback: true,
        submitEarlyAccessFeatureFeedback: (message: string) => ({ message }),
    }),
    loaders(({ values }) => ({
        rawEarlyAccessFeatures: [
            [] as EarlyAccessFeature[],
            {
                loadEarlyAccessFeatures: async () => {
                    return await new Promise((resolve) =>
                        posthog.getEarlyAccessFeatures((features) => resolve(features), true)
                    )
                },
            },
        ],
        activeFeedbackFlagKey: [
            null as string | null,
            {
                submitEarlyAccessFeatureFeedback: async ({ message }) => {
                    if (!values.user) {
                        throw new Error('Cannot submit early access feature feedback without a user')
                    }
                    if (!values.activeFeedbackFlagKey) {
                        throw new Error('Cannot submit early access feature feedback without an active flag key')
                    }
                    await supportLogic.asyncActions.submitZendeskTicket(
                        values.user.first_name,
                        values.user.email,
                        'feedback',
                        values.activeFeedbackFlagKey,
                        message
                    )
                    return null
                },
            },
        ],
    })),
    reducers({
        featurePreviewsModalVisible: [
            false,
            {
                showFeaturePreviewsModal: () => true,
                hideFeaturePreviewsModal: () => false,
            },
        ],
        activeFeedbackFlagKey: {
            beginEarlyAccessFeatureFeedback: (_, { flagKey }) => flagKey,
            cancelEarlyAccessFeatureFeedback: () => null,
            hideFeaturePreviewsModal: () => null,
        },
    }),
    listeners(() => ({
        updateEarlyAccessFeatureEnrollment: ({ flagKey, enabled }) => {
            posthog.updateEarlyAccessFeatureEnrollment(flagKey, enabled)
        },
    })),
    selectors({
        earlyAccessFeatures: [
            (s) => [s.rawEarlyAccessFeatures, s.featureFlags],
            (rawEarlyAccessFeatures, featureFlags): EnrichedEarlyAccessFeature[] =>
                rawEarlyAccessFeatures
                    .filter((feature) => {
                        if (!feature.flagKey) {
                            return false // Filter out features without a flag linked
                        }
                        if (CONSTRAINED_PREVIEWS.has(feature.flagKey as FeatureFlagKey)) {
                            return !!featureFlags[`${feature.flagKey}-preview`]
                        }
                        return true
                    })
                    .map((feature) => {
                        if (!feature.flagKey) {
                            throw new Error('Early access feature without flagKey was not filtered out')
                        }
                        return {
                            ...feature,
                            flagKey: feature.flagKey,
                            enabled: !!featureFlags[feature.flagKey],
                        }
                    }),
        ],
    }),
])
