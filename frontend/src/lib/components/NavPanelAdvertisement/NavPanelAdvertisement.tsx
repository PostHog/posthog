import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { BroadcastPayload, isBroadcastPayload } from './navPanelAdShared'
import { NavPanelBroadcastAd } from './NavPanelBroadcastAd'
import { NavPanelProductPushAd } from './NavPanelProductPushAd'
import { navPanelProductPushLogic } from './navPanelProductPushLogic'

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

    return null
}
