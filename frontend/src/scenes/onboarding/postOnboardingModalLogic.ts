import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { globalSetupLogic } from 'lib/components/ProductSetup/globalSetupLogic'
import { getProductSetupConfig } from 'lib/components/ProductSetup/productSetupRegistry'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import type { postOnboardingModalLogicType } from './postOnboardingModalLogicType'

export const postOnboardingModalLogic = kea<postOnboardingModalLogicType>([
    path(['scenes', 'onboarding', 'postOnboardingModalLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags', 'receivedFeatureFlags']],
        actions: [globalSetupLogic, ['openGlobalSetup', 'closeGlobalSetup']],
    })),
    actions({
        openPostOnboardingModal: (productKey: ProductKey) => ({ productKey }),
        closePostOnboardingModal: true,
        ctaClicked: true,
        dismissModal: (method: 'close_button' | 'explore_on_my_own') => ({ method }),
    }),
    reducers({
        isModalOpen: [
            false,
            {
                openPostOnboardingModal: () => true,
                closePostOnboardingModal: () => false,
            },
        ],
        modalShown: [
            false,
            { persist: true },
            {
                openPostOnboardingModal: () => true,
            },
        ],
        onboardedProductKey: [
            null as ProductKey | null,
            {
                openPostOnboardingModal: (_, { productKey }) => productKey,
                closePostOnboardingModal: () => null,
            },
        ],
        modalOpenedAt: [
            null as number | null,
            {
                openPostOnboardingModal: () => Date.now(),
                closePostOnboardingModal: () => null,
            },
        ],
    }),
    selectors({
        isExperimentVariant: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => featureFlags[FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT] === 'test',
        ],
        experimentVariant: [
            (s) => [s.featureFlags],
            (featureFlags): string =>
                (featureFlags[FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT] as string) ?? 'control',
        ],
        productSetupConfig: [
            (s) => [s.onboardedProductKey],
            (productKey) => (productKey ? getProductSetupConfig(productKey) : null),
        ],
    }),
    listeners(({ actions, values }) => ({
        openPostOnboardingModal: ({ productKey }) => {
            const taskCount = values.productSetupConfig?.tasks?.length ?? 0
            posthog.capture('post_onboarding_modal_shown', {
                product_key: productKey,
                variant: values.experimentVariant,
                task_count: taskCount,
            })
            actions.closeGlobalSetup()
        },
        ctaClicked: () => {
            const durationMs = values.modalOpenedAt ? Date.now() - values.modalOpenedAt : null
            posthog.capture('post_onboarding_modal_cta_clicked', {
                product_key: values.onboardedProductKey,
                variant: values.experimentVariant,
                time_on_modal_ms: durationMs,
            })
            actions.closePostOnboardingModal()
            actions.openGlobalSetup()
        },
        dismissModal: ({ method }) => {
            const durationMs = values.modalOpenedAt ? Date.now() - values.modalOpenedAt : null
            posthog.capture('post_onboarding_modal_dismissed', {
                product_key: values.onboardedProductKey,
                variant: values.experimentVariant,
                dismiss_method: method,
                time_on_modal_ms: durationMs,
            })
            actions.closePostOnboardingModal()
        },
    })),
])
