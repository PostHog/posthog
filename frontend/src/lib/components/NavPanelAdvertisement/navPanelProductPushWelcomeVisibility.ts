import type { ProductEmptyStateGateRender } from 'lib/components/ProductEmptyState/gateRender'

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
    /** What the active scene's setup gate puts on screen, or null if no gate covers the pushed product. */
    pushedProductGate: ProductEmptyStateGateRender | null
}

/**
 * Product analytics is the case this exists for: every project sends events, so its setup screen
 * never shows and the click ends on a full insight list that says nothing about why the user is there.
 */
export function shouldShowProductPushWelcome({
    pending,
    activeSceneProductKey,
    pushedProductGate,
}: ProductPushWelcomeVisibility): boolean {
    if (!pending) {
        return false
    }
    // The click starts a navigation, so hold the modal back until the pushed product's own scene is
    // the one on screen. It also keeps the modal off surfaces that are not products, such as the
    // integration settings pages the Slack and GitHub cards link to. A scene can belong to one
    // product and gate on another - the dashboard list sits under product analytics and gates on
    // dashboards - so either side identifying the product counts as arriving.
    if (activeSceneProductKey !== pending.productKey && !pushedProductGate) {
        return false
    }
    if (!pushedProductGate) {
        return true
    }
    // The modal stands in for the setup screen, so it waits for the gate to hand the scene through.
    return pushedProductGate === 'scene'
}
