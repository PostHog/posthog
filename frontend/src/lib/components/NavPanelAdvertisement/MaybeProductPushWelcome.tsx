import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import {
    EMPTY_STATE_PARAM,
    forcedModeFromParam,
    productEmptyStateGateRender,
} from 'lib/components/ProductEmptyState/gateRender'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { navPanelProductPushWelcomeLogic } from './navPanelProductPushWelcomeLogic'
import { type PendingProductPushWelcome, shouldShowProductPushWelcome } from './navPanelProductPushWelcomeVisibility'
import { ProductPushWelcomeModal } from './ProductPushWelcomeModal'

/**
 * Mounted in GlobalModals so it survives the navigation the advertisement click starts, and mounts
 * nothing at all until a click has something to follow up on.
 */
export function MaybeProductPushWelcome(): JSX.Element | null {
    const { pending, openFor } = useValues(navPanelProductPushWelcomeLogic)

    // The setup status below is keyed by product, so the card being introduced has to be known
    // before any of it can be mounted.
    const welcome = openFor ?? pending
    if (!welcome) {
        return null
    }
    return <ProductPushWelcome welcome={welcome} isOpen={!!openFor} />
}

function ProductPushWelcome({
    welcome,
    isOpen,
}: {
    welcome: PendingProductPushWelcome
    isOpen: boolean
}): JSX.Element | null {
    const { activeExportedScene, activeSceneProductKey, activeSceneId, activeSceneComponentParams } =
        useValues(sceneLogic)
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)
    const { status, skipped } = useValues(productSetupStatusLogic({ productKey: welcome.productKey }))
    const { openWelcome, closeWelcome } = useActions(navPanelProductPushWelcomeLogic)

    const sceneEmptyState = activeExportedScene?.emptyState
    const gatesPushedProduct = sceneEmptyState?.config.productKey === welcome.productKey
    // The gate renders more than the setup status: `?empty_state=1` forces the screen onto a product
    // that has data, and a flag or a `scenes` scope takes it away from a product that has none.
    const ready = shouldShowProductPushWelcome({
        pending: welcome,
        activeSceneProductKey,
        pushedProductGate:
            sceneEmptyState && gatesPushedProduct
                ? productEmptyStateGateRender({
                      emptyState: sceneEmptyState,
                      activeSceneId,
                      params: activeSceneComponentParams,
                      featureFlags,
                      receivedFeatureFlags,
                      forcedMode: forcedModeFromParam(searchParams[EMPTY_STATE_PARAM]),
                      status,
                      skipped,
                  })
                : null,
    })

    useEffect(() => {
        if (!isOpen && ready) {
            openWelcome(welcome)
        }
    }, [isOpen, ready, welcome, openWelcome])

    if (!isOpen) {
        return null
    }
    const config = gatesPushedProduct ? sceneEmptyState?.config : undefined
    return <ProductPushWelcomeModal welcome={welcome} config={config} onClose={closeWelcome} />
}
