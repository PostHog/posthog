import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { BroadcastPayload, isBroadcastPayload } from './navPanelAdShared'
import { NavPanelBroadcastAd } from './NavPanelBroadcastAd'
import { NavPanelMcpAd } from './NavPanelMcpAd'
import { NavPanelProductPushAd } from './NavPanelProductPushAd'
import { navPanelProductPushLogic } from './navPanelProductPushLogic'

// Growth owns this sidebar promotion slot and every card in it. Other teams must not add cards to the slot
// or change which card wins it. Ask #team-growth to run a promotion for your product instead.
export function NavPanelAdvertisement(): JSX.Element | null {
    const { activeCampaign } = useValues(navPanelProductPushLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { user } = useValues(userLogic)

    const broadcastPayload = getFeatureFlagPayload(FEATURE_FLAGS.NAV_PANEL_BROADCAST) as BroadcastPayload | undefined

    if (isLayoutNavCollapsed) {
        return null
    }

    // A hand-authored broadcast outranks the scheduler, so a deliberate message is never preempted
    // by an automated push. Both cards promote cloud features, so neither is shown on hobby.
    if (isCloudOrDev && isBroadcastPayload(broadcastPayload)) {
        return <NavPanelBroadcastAd broadcast={broadcastPayload} />
    }

    // The org-wide product push campaign, driven by the growth backend. Respects the
    // user's "no product suggestions" setting.
    if (isCloudOrDev && activeCampaign && user?.allow_sidebar_suggestions !== false) {
        return <NavPanelProductPushAd campaign={activeCampaign} />
    }

    // Fills the gaps between campaigns. The MCP server only serves cloud and dev instances.
    if (isCloudOrDev && user) {
        return <NavPanelMcpAd />
    }

    return null
}
