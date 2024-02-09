import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { FeatureFlagKey } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { EarlyAccessFeature, posthog } from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import type { featurePreviewsLogicType } from './featurePreviewsLogicType'

/** Features that can only be toggled if you fall under the `${flagKey}-preview` flag */
export const CONSTRAINED_PREVIEWS: Set<FeatureFlagKey> = new Set([])

export interface EnrichedEarlyAccessFeature extends Omit<EarlyAccessFeature, 'flagKey'> {
    flagKey: string
    enabled: boolean
}

export const featurePreviewsLogic = kea<featurePreviewsLogicType>([
    path(['layout', 'FeaturePreviews', 'featurePreviewsLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['user']],
        actions: [supportLogic, ['submitZendeskTicket']],
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
                    await supportLogic.asyncActions.submitZendeskTicket({
                        name: values.user.first_name,
                        email: values.user.email,
                        kind: 'feedback',
                        // NOTE: We don't know which area the flag should be - for now we just override it to be the key...
                        target_area: values.activeFeedbackFlagKey as any,
                        severity_level: 'low',
                        message,
                    })
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
    urlToAction(({ actions }) => ({
        '*': (_, _search, hashParams) => {
            if (hashParams['panel'] === 'feature-previews') {
                actions.showFeaturePreviewsModal()
            }
        },
    })),
    actionToUrl(() => {
        return {
            showFeaturePreviewsModal: () => {
                const hashParams = router.values.hashParams
                hashParams['panel'] = 'feature-previews'
                return [router.values.location.pathname, router.values.searchParams, hashParams]
            },
            hideFeaturePreviewsModal: () => {
                const hashParams = router.values.hashParams
                delete hashParams['panel']
                return [router.values.location.pathname, router.values.searchParams, hashParams]
            },
        }
    }),
])
