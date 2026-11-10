import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { BroadcastPayload, NavPanelSlot, SIDEBAR_SLOT, isBroadcastPayload } from './navPanelAdShared'
import { NavPanelBroadcastAd } from './NavPanelBroadcastAd'
import { NavPanelMcpAd } from './NavPanelMcpAd'
import { NavPanelProductPushAd } from './NavPanelProductPushAd'
import { navPanelProductPushLogic } from './navPanelProductPushLogic'

// Growth owns this promotion slot, in the classic sidebar and on the Today rail, and every card in it. Other teams must not add cards to the slot
// or change which card wins it. Ask #team-growth to run a promotion for your product instead.
export function NavPanelAdvertisement({ slot = SIDEBAR_SLOT }: { slot?: NavPanelSlot }): JSX.Element | null {
    const { activeCampaign } = useValues(navPanelProductPushLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { user } = useValues(userLogic)

    const broadcastPayload = getFeatureFlagPayload(FEATURE_FLAGS.NAV_PANEL_BROADCAST) as BroadcastPayload | undefined

    // A hand-authored broadcast outranks the scheduler, so a deliberate message is never preempted
    // by an automated push. Both cards promote cloud features, so neither is shown on hobby.
    if (isCloudOrDev && isBroadcastPayload(broadcastPayload)) {
        return <NavPanelBroadcastAd broadcast={broadcastPayload} slot={slot} />
    }

    // The org-wide product push campaign, driven by the growth backend. Respects the
    // user's "no product suggestions" setting.
    if (isCloudOrDev && activeCampaign && user?.allow_sidebar_suggestions !== false) {
        return <NavPanelProductPushAd campaign={activeCampaign} slot={slot} />
    }

    // Fills the gaps between campaigns. The MCP server only serves cloud and dev instances.
    if (isCloudOrDev && user) {
        return <NavPanelMcpAd slot={slot} />
    }

    return null
}
