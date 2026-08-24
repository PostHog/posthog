import { FeaturePreviewGateConfig } from '~/types'

import { customerAnalyticsFeaturePreviewGate } from 'products/customer_analytics/frontend/featurePreviewGate'
import { mcpAnalyticsFeaturePreviewGate } from 'products/mcp_analytics/frontend/featurePreviewGate'
import { metricsFeaturePreviewGate } from 'products/metrics/frontend/featurePreviewGate'

// Gate configs keyed by flag. The settings card uses these to fall back to a product's own
// docs URL and description when the early access feature record leaves those fields empty.
export const FEATURE_PREVIEW_GATES: Record<string, FeaturePreviewGateConfig> = Object.fromEntries(
    [customerAnalyticsFeaturePreviewGate, mcpAnalyticsFeaturePreviewGate, metricsFeaturePreviewGate].map((gate) => [
        gate.flag,
        gate,
    ])
)
