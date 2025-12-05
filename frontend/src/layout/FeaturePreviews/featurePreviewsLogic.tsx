import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { EarlyAccessFeature, posthog } from 'posthog-js'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FeatureFlagKey } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { featurePreviewsLogicType } from './featurePreviewsLogicType'

export interface EnrichedEarlyAccessFeature extends Omit<EarlyAccessFeature, 'flagKey'> {
    flagKey: string
    enabled: boolean
    payload: Record<string, any> | undefined
}

export const featurePreviewsLogic = kea<featurePreviewsLogicType>([
    path(['layout', 'FeaturePreviews', 'featurePreviewsLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['user']],
        actions: [supportLogic, ['submitZendeskTicket'], teamLogic, ['addProductIntentForCrossSell']],
    })),
    actions({
        updateEarlyAccessFeatureEnrollment: (flagKey: string, enabled: boolean, stage?: string) => ({
            flagKey,
            enabled,
            stage,
        }),
        beginEarlyAccessFeatureFeedback: (flagKey: string) => ({ flagKey }),
        cancelEarlyAccessFeatureFeedback: true,
        submitEarlyAccessFeatureFeedback: (message: string) => ({ message }),
        copyExternalFeaturePreviewLink: (flagKey: string) => ({ flagKey }),
    }),
    loaders(({ values }) => ({
        rawEarlyAccessFeatures: [
            [] as EarlyAccessFeature[],
            {
                loadEarlyAccessFeatures: async () => {
                    return await new Promise((resolve) =>
                        posthog.getEarlyAccessFeatures((features) => resolve(features), true, ['concept', 'beta'])
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
        activeFeedbackFlagKey: {
            beginEarlyAccessFeatureFeedback: (_, { flagKey }) => flagKey,
            cancelEarlyAccessFeatureFeedback: () => null,
        },
    }),
    listeners(({ values, actions }) => ({
        updateEarlyAccessFeatureEnrollment: ({ flagKey, enabled, stage }) => {
            if (window.IMPERSONATED_SESSION) {
                lemonToast.error('Cannot update early access feature enrollment while impersonating a user')
            } else {
                posthog.updateEarlyAccessFeatureEnrollment(flagKey, enabled, stage)

                // Track product intent if user is opting in and payload contains product_intent
                // The format on the payload should be: { product_intent: ProductKey }
                if (enabled) {
                    const feature = values.rawEarlyAccessFeatures.find((f) => f.flagKey === flagKey)

                    // TODO: We can stop using this crazy type cast once the companion `posthog-js` PR is merged
                    // https://github.com/PostHog/posthog-js/pull/2642
                    const payload = (feature as any)?.payload as Record<string, any> | undefined
                    if (payload?.product_intent) {
                        const productIntent = payload.product_intent

                        if (
                            productIntent &&
                            typeof productIntent === 'string' &&
                            Object.values(ProductKey).includes(productIntent as ProductKey)
                        ) {
                            void actions.addProductIntentForCrossSell({
                                from: ProductKey.EARLY_ACCESS_FEATURES,
                                to: productIntent as ProductKey,
                                intent_context: ProductIntentContext.FEATURE_PREVIEW_ENABLED,
                            })
                        }
                    }
                }
            }
        },
        copyExternalFeaturePreviewLink: ({ flagKey }) => {
            void copyToClipboard(urls.absolute(`/settings/user-feature-previews#${flagKey}`))
        },
    })),
    selectors({
        earlyAccessFeatures: [
            (s) => [s.rawEarlyAccessFeatures, s.featureFlags],
            (rawEarlyAccessFeatures, featureFlags): EnrichedEarlyAccessFeature[] => {
                const result = rawEarlyAccessFeatures
                    .filter((feature) => !!feature.flagKey) // Filter out features without a flag linked
                    .map((feature) => {
                        const flagKey = feature.flagKey! as FeatureFlagKey
                        const flag = featureFlags[flagKey]

                        return {
                            ...feature,
                            flagKey,
                            // Use payload from early access feature, fallback to empty object
                            payload: ((feature as any).payload as Record<string, any> | undefined) || {},
                            enabled: !!flag,
                        }
                    })

                return result
            },
        ],
    }),
])
