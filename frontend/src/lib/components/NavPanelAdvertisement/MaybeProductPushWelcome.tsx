import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
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
    const { activeExportedScene, activeSceneProductKey } = useValues(sceneLogic)
    const { status, skipped } = useValues(productSetupStatusLogic({ productKey: welcome.productKey }))
    const { openWelcome, closeWelcome } = useActions(navPanelProductPushWelcomeLogic)

    const sceneEmptyState = activeExportedScene?.emptyState
    const ready = shouldShowProductPushWelcome({
        pending: welcome,
        activeSceneProductKey,
        sceneEmptyState,
        status,
        skipped,
    })

    useEffect(() => {
        if (!isOpen && ready) {
            openWelcome(welcome)
        }
    }, [isOpen, ready, welcome, openWelcome])

    if (!isOpen) {
        return null
    }
    const config = sceneEmptyState?.config.productKey === welcome.productKey ? sceneEmptyState.config : undefined
    return <ProductPushWelcomeModal welcome={welcome} config={config} onClose={closeWelcome} />
}
