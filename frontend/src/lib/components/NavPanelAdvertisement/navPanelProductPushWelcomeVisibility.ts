import type { ProductSetupStatus, SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import type { ProductKey } from '~/queries/schema/schema-general'

export interface PendingProductPushWelcome {
    campaignId: string
    productKey: ProductKey
    label: string
    /** The blurb the card showed, which is the campaign's reason text when it set one. */
    text: string
}

export interface ProductPushWelcomeVisibility {
    pending: PendingProductPushWelcome | null
    activeSceneProductKey: ProductKey | null
    sceneEmptyState: SceneProductEmptyState | undefined
    /** Both read from `productSetupStatusLogic` for the pushed product. */
    status: ProductSetupStatus
    skipped: boolean
}

/**
 * Product analytics is the case this exists for: every project sends events, so its setup screen
 * never shows and the click ends on a full insight list that says nothing about why the user is there.
 */
export function shouldShowProductPushWelcome({
    pending,
    activeSceneProductKey,
    sceneEmptyState,
    status,
    skipped,
}: ProductPushWelcomeVisibility): boolean {
    if (!pending) {
        return false
    }
    const gate = sceneEmptyState?.config
    // The click starts a navigation, so hold the modal back until the pushed product's own scene is
    // the one on screen. It also keeps the modal off surfaces that are not products, such as the
    // integration settings pages the Slack and GitHub cards link to. A scene can belong to one
    // product and gate on another - the dashboard list sits under product analytics and gates on
    // dashboards - so either side identifying the product counts as arriving.
    if (activeSceneProductKey !== pending.productKey && gate?.productKey !== pending.productKey) {
        return false
    }
    if (gate?.productKey !== pending.productKey) {
        return true
    }
    // Mirrors the gate's own reading of a stored skip, which a non-skippable product ignores.
    if (skipped && gate.skippable !== false) {
        return true
    }
    // `loading` holds the modal back rather than opening it in front of a setup screen that is still
    // resolving. The gate fails open on `unknown`, so the scene renders and the modal is needed again.
    return status === 'has-data' || status === 'unknown'
}
