import { ProductKey } from '~/queries/schema/schema-general'

import { dataWarehouseOnboardingSteps } from 'products/data_warehouse/frontend/onboarding/steps'
import { errorTrackingOnboardingSteps } from 'products/error_tracking/frontend/onboarding/steps'
import { experimentsOnboardingSteps } from 'products/experiments/frontend/onboarding/steps'
import { featureFlagsOnboardingSteps } from 'products/feature_flags/frontend/onboarding/steps'
import { llmAnalyticsOnboardingSteps } from 'products/llm_analytics/frontend/onboarding/steps'
import { logsOnboardingSteps } from 'products/logs/frontend/onboarding/steps'
import { productAnalyticsOnboardingSteps } from 'products/product_analytics/frontend/onboarding/steps'
import { sessionReplayOnboardingSteps } from 'products/session_replay/frontend/onboarding/steps'
import { surveysOnboardingSteps } from 'products/surveys/frontend/onboarding/steps'
import { webAnalyticsOnboardingSteps } from 'products/web_analytics/frontend/onboarding/steps'
import { workflowsOnboardingSteps } from 'products/workflows/frontend/onboarding/steps'

import { type StepProvider } from './types'

/**
 * Registry of per-product step providers. The flow selector iterates `selectedProducts`
 * in order and concatenates each provider's contribution into a single flat flow.
 *
 * Adding a product to the onboarding system: write a provider in
 * `products/<name>/frontend/onboarding/steps.tsx`, register it here, and add the
 * product to `availableOnboardingProducts` in `utils.tsx`.
 */
export const stepProviderRegistry: Partial<Record<ProductKey, StepProvider>> = {
    [ProductKey.PRODUCT_ANALYTICS]: productAnalyticsOnboardingSteps,
    [ProductKey.WEB_ANALYTICS]: webAnalyticsOnboardingSteps,
    [ProductKey.SESSION_REPLAY]: sessionReplayOnboardingSteps,
    [ProductKey.FEATURE_FLAGS]: featureFlagsOnboardingSteps,
    [ProductKey.EXPERIMENTS]: experimentsOnboardingSteps,
    [ProductKey.SURVEYS]: surveysOnboardingSteps,
    [ProductKey.DATA_WAREHOUSE]: dataWarehouseOnboardingSteps,
    [ProductKey.ERROR_TRACKING]: errorTrackingOnboardingSteps,
    [ProductKey.LLM_ANALYTICS]: llmAnalyticsOnboardingSteps,
    [ProductKey.WORKFLOWS]: workflowsOnboardingSteps,
    [ProductKey.LOGS]: logsOnboardingSteps,
}
