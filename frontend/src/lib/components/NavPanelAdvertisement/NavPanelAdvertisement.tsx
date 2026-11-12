import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { NAV_PANEL_CARD_TYPE, NAV_PANEL_PLACEMENT } from './navPanelAdShared'
import { NavPanelBroadcastAd } from './NavPanelBroadcastAd'
import { NavPanelMcpAd } from './NavPanelMcpAd'
import { NavPanelProductPushAd } from './NavPanelProductPushAd'
import { navPanelProductPushLogic } from './navPanelProductPushLogic'
import { pickNavPanelSlotCard } from './navPanelSlotCard'

// Growth owns this sidebar promotion slot and every card in it. Other teams must not add cards to the slot
// or change which card wins it. Ask #team-growth to run a promotion for your product instead.
export function NavPanelAdvertisement(): JSX.Element | null {
    const { activeCampaign, activeCampaignResolved } = useValues(navPanelProductPushLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { user } = useValues(userLogic)

    if (isLayoutNavCollapsed) {
        return null
    }

    const card = pickNavPanelSlotCard({
        isCloudOrDev,
        broadcastPayload: getFeatureFlagPayload(FEATURE_FLAGS.NAV_PANEL_BROADCAST),
        activeCampaign,
        campaignResolved: activeCampaignResolved,
        user,
    })

    switch (card?.type) {
        case NAV_PANEL_CARD_TYPE.BROADCAST:
            return <NavPanelBroadcastAd broadcast={card.broadcast} placement={NAV_PANEL_PLACEMENT.SIDEBAR} />
        case NAV_PANEL_CARD_TYPE.PRODUCT_PUSH:
            return <NavPanelProductPushAd campaign={card.campaign} />
        case NAV_PANEL_CARD_TYPE.MCP_CONNECT:
            return <NavPanelMcpAd placement={NAV_PANEL_PLACEMENT.SIDEBAR} />
        default:
            return null
    }
}
