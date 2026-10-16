import type { LogicWrapper } from 'kea'

import { productEmptyStateGateActivation } from 'lib/components/ProductEmptyState/gateRender'
import type { ProductEmptyStateConfig } from 'lib/components/ProductEmptyState/types'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { appScenes } from 'scenes/appScenes'
import type { Scene, SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

export interface WelcomeEmptyState {
    config: ProductEmptyStateConfig
    /**
     * The product's detection logic, which pushes its status into `productSetupStatusLogic`. Null
     * when the welcome page detects the status itself, because the product's shared status means
     * something else (web analytics' belongs to the web vitals tab).
     */
    statusLogic: LogicWrapper | null
}

/**
 * The setup screen a product's landing scene would show, or null when that scene shows none for
 * this product. A scene can declare an empty state for a different product or for one of its other
 * tabs (web analytics declares the web vitals one), and the welcome page must not show those.
 */
export function pickWelcomeEmptyState(
    sceneExport: SceneExport | undefined,
    productKey: ProductKey,
    sceneId: Scene,
    featureFlags: FeatureFlagsSet
): WelcomeEmptyState | null {
    const emptyState = sceneExport?.emptyState
    if (!emptyState || emptyState.config.productKey !== productKey) {
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
    return activation === 'on' ? { config: emptyState.config, statusLogic: emptyState.statusLogic } : null
}

export async function loadWelcomeEmptyState(
    productKey: ProductKey,
    sceneId: Scene,
    featureFlags: FeatureFlagsSet
): Promise<WelcomeEmptyState | null> {
    try {
        if (productKey === ProductKey.WEB_ANALYTICS) {
            const { webAnalyticsEmptyStateConfig } =
                await import('products/web_analytics/frontend/emptyState/webAnalyticsEmptyState')
            return { config: webAnalyticsEmptyStateConfig, statusLogic: null }
        }
        const importScene = appScenes[sceneId]
        if (!importScene) {
            return null
        }
        const sceneModule = await importScene()
        return pickWelcomeEmptyState(sceneModule.scene, productKey, sceneId, featureFlags)
    } catch {
        return null
    }
}
