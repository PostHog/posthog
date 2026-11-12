import type { UserType } from '~/types'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { BroadcastPayload, NAV_PANEL_CARD_TYPE, isBroadcastPayload } from './navPanelAdShared'

export type NavPanelSlotCard =
    | { type: typeof NAV_PANEL_CARD_TYPE.BROADCAST; broadcast: BroadcastPayload }
    | { type: typeof NAV_PANEL_CARD_TYPE.PRODUCT_PUSH; campaign: ProductPushCampaignApi }
    | { type: typeof NAV_PANEL_CARD_TYPE.MCP_CONNECT }

/** A dismissed winner leaves the slot empty instead of handing it to the next card. */
export function pickNavPanelSlotCard({
    isCloudOrDev,
    broadcastPayload,
    activeCampaign,
    campaignResolved,
    user,
}: {
    isCloudOrDev: boolean | undefined
    broadcastPayload: unknown
    activeCampaign: ProductPushCampaignApi | null
    campaignResolved: boolean
    user: UserType | null
}): NavPanelSlotCard | null {
    if (!isCloudOrDev) {
        return null
    }

    // A hand-authored broadcast outranks the scheduler, so an automated push never preempts a deliberate message.
    if (isBroadcastPayload(broadcastPayload)) {
        return { type: NAV_PANEL_CARD_TYPE.BROADCAST, broadcast: broadcastPayload }
    }

    if (activeCampaign && user?.allow_sidebar_suggestions !== false) {
        return { type: NAV_PANEL_CARD_TYPE.PRODUCT_PUSH, campaign: activeCampaign }
    }

    return user && campaignResolved ? { type: NAV_PANEL_CARD_TYPE.MCP_CONNECT } : null
}
