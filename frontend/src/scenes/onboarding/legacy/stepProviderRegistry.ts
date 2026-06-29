import { ProductKey } from '~/queries/schema/schema-general'

import { aiObservabilityOnboarding } from 'products/ai_observability/frontend/onboarding/steps'
import { dataWarehouseOnboarding } from 'products/data_warehouse/frontend/onboarding/steps'
import { errorTrackingOnboarding } from 'products/error_tracking/frontend/onboarding/steps'
import { experimentsOnboarding } from 'products/experiments/frontend/onboarding/steps'
import { featureFlagsOnboarding } from 'products/feature_flags/frontend/onboarding/steps'
import { logsOnboarding } from 'products/logs/frontend/onboarding/steps'
import { mcpAnalyticsOnboarding } from 'products/mcp_analytics/frontend/onboarding/steps'
import { productAnalyticsOnboarding } from 'products/product_analytics/frontend/onboarding/steps'
import { sessionReplayOnboarding } from 'products/session_replay/frontend/onboarding/steps'
import { surveysOnboarding } from 'products/surveys/frontend/onboarding/steps'
import { webAnalyticsOnboarding } from 'products/web_analytics/frontend/onboarding/steps'
import { workflowsOnboarding } from 'products/workflows/frontend/onboarding/steps'

import { type ProductOnboardingProvider } from './types'

/**
 * Registry of per-product onboarding providers. The flow selector iterates
 * `selectedProducts` in order and concatenates each provider's `steps(ctx)`
 * into a single flat flow. The primary product's `completeRedirectUrl()` is
 * used as the post-onboarding landing target.
 *
 * Adding a product to the onboarding system: write a provider in
 * `products/<name>/frontend/onboarding/steps.tsx`, register it here, and add
 * the product to `availableOnboardingProducts` in `utils.tsx`.
 */
export const onboardingProviderRegistry: Partial<Record<ProductKey, ProductOnboardingProvider>> = {
    [ProductKey.PRODUCT_ANALYTICS]: productAnalyticsOnboarding,
    [ProductKey.WEB_ANALYTICS]: webAnalyticsOnboarding,
    [ProductKey.SESSION_REPLAY]: sessionReplayOnboarding,
    [ProductKey.FEATURE_FLAGS]: featureFlagsOnboarding,
    [ProductKey.EXPERIMENTS]: experimentsOnboarding,
    [ProductKey.SURVEYS]: surveysOnboarding,
    [ProductKey.DATA_WAREHOUSE]: dataWarehouseOnboarding,
    [ProductKey.ERROR_TRACKING]: errorTrackingOnboarding,
    [ProductKey.AI_OBSERVABILITY]: aiObservabilityOnboarding,
    [ProductKey.WORKFLOWS]: workflowsOnboarding,
    [ProductKey.LOGS]: logsOnboarding,
    [ProductKey.MCP_ANALYTICS]: mcpAnalyticsOnboarding,
}
