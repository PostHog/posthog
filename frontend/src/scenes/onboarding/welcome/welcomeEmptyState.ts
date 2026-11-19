import { productEmptyStateGateActivation } from 'lib/components/ProductEmptyState/gateRender'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { retryImport } from 'lib/utils/retryImport'
import type { Scene } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'
import type { AvailableOnboardingProducts } from '~/types'

// Each product's setup screen on its own, so picking a product does not download its whole scene.
const EMPTY_STATE_IMPORTS: Record<keyof AvailableOnboardingProducts, () => Promise<SceneProductEmptyState>> = {
    [ProductKey.PRODUCT_ANALYTICS]: async () =>
        (await import('products/product_analytics/frontend/emptyState/productAnalyticsEmptyState'))
            .productAnalyticsEmptyState,
    [ProductKey.WEB_ANALYTICS]: async () =>
        (await import('products/web_analytics/frontend/emptyState/webAnalyticsEmptyState')).webAnalyticsEmptyState,
    [ProductKey.SESSION_REPLAY]: async () =>
        (await import('products/replay/frontend/emptyState/sessionReplayEmptyState')).sessionReplayEmptyState,
    [ProductKey.AI_OBSERVABILITY]: async () =>
        (await import('products/ai_observability/frontend/emptyState/aiObservabilityEmptyState'))
            .aiObservabilityEmptyState,
    [ProductKey.DATA_WAREHOUSE]: async () =>
        (await import('products/data_warehouse/frontend/emptyState/dataWarehouseEmptyState')).dataWarehouseEmptyState,
    [ProductKey.FEATURE_FLAGS]: async () =>
        (await import('products/feature_flags/frontend/emptyState/featureFlagsEmptyState')).featureFlagsEmptyState,
    [ProductKey.EXPERIMENTS]: async () =>
        (await import('products/experiments/frontend/emptyState/experimentsEmptyState')).experimentsEmptyState,
    [ProductKey.ERROR_TRACKING]: async () =>
        (await import('products/error_tracking/frontend/emptyState/errorTrackingEmptyState')).errorTrackingEmptyState,
    [ProductKey.SURVEYS]: async () =>
        (await import('products/surveys/frontend/emptyState/surveysEmptyState')).surveysEmptyState,
    [ProductKey.WORKFLOWS]: async () =>
        (await import('products/workflows/frontend/emptyState/workflowsEmptyState')).workflowsEmptyState,
    [ProductKey.LOGS]: async () => (await import('products/logs/frontend/emptyState/logsEmptyState')).logsEmptyState,
    [ProductKey.METRICS]: async () =>
        (await import('products/metrics/frontend/emptyState/metricsEmptyState')).metricsEmptyState,
    [ProductKey.MCP_ANALYTICS]: async () =>
        (await import('products/mcp_analytics/frontend/emptyState/mcpAnalyticsEmptyState')).mcpAnalyticsEmptyState,
    [ProductKey.CONVERSATIONS]: async () =>
        (await import('products/conversations/frontend/emptyState/supportEmptyState')).supportEmptyState,
}

/**
 * The setup screen the product's landing scene would show, or null when that scene would not show it
 * (a feature flag or a scene restriction turns it off).
 */
export function pickWelcomeEmptyState(
    emptyState: SceneProductEmptyState,
    productKey: ProductKey,
    sceneId: Scene,
    featureFlags: FeatureFlagsSet
): SceneProductEmptyState | null {
    if (emptyState.config.productKey !== productKey) {
        return null
    }
    const activation = productEmptyStateGateActivation({
        emptyState,
        activeSceneId: sceneId,
        params: {},
        featureFlags,
        receivedFeatureFlags: true,
        forcedMode: null,
    })
    return activation === 'on' ? emptyState : null
}

export async function loadWelcomeEmptyState(
    productKey: keyof AvailableOnboardingProducts,
    sceneId: Scene,
    featureFlags: FeatureFlagsSet
): Promise<SceneProductEmptyState | null> {
    try {
        const emptyState = await retryImport(EMPTY_STATE_IMPORTS[productKey])
        return pickWelcomeEmptyState(emptyState, productKey, sceneId, featureFlags)
    } catch {
        return null
    }
}
