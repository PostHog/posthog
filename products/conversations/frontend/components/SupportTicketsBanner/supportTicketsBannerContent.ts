import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { BusinessKnowledgeSettingsApi } from 'products/business_knowledge/frontend/generated/api.schemas'

export const SELF_LEARNING_DISMISS_KEY = 'support-self-learning-banner'

/** The self-learning banner reads a flag-gated settings endpoint, so only these flags let it load. */
export function selfLearningBannerAvailable(featureFlags: FeatureFlagsSet): boolean {
    return (
        !!featureFlags[FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE] &&
        !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_AI_SUGGESTION_ORGS]
    )
}

export function showSelfLearningBanner(settings: BusinessKnowledgeSettingsApi | null, isDismissed: boolean): boolean {
    return !isDismissed && !!settings && settings.support_enabled && !settings.learn_from_support_enabled
}

export interface FeedbackBannerContent {
    dismissKey: string
    /** pinned: a survey targets the button by this id */
    buttonId: string
    text: string
}

export function feedbackBannerContent(aiEnabled: boolean): FeedbackBannerContent {
    // pinned: survey 01a17c76-69b3-0000-bb24-4adfd734f406 targets #ai-support-feedback-button
    return aiEnabled
        ? {
              dismissKey: 'ai-support-feedback-banner',
              buttonId: 'ai-support-feedback-button',
              text: 'Tell us how the AI agent is working, or report any issues.',
          }
        : {
              dismissKey: 'support-feedback-banner',
              buttonId: 'support-feedback-button',
              text: 'Tell us how the support product is working, or report any issues.',
          }
}
