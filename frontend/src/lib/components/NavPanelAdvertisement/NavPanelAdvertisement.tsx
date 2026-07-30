import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { CampaignPayload, isCampaignPayload } from './navPanelAdShared'
import { navPanelAdvertisementRecommendedLogic } from './navPanelAdvertisementRecommendedLogic'
import { NavPanelCampaignAd } from './NavPanelCampaignAd'
import { NavPanelCmdKAd } from './NavPanelCmdKAd'
import { NavPanelProductPushAd } from './NavPanelProductPushAd'
import { navPanelProductPushLogic } from './navPanelProductPushLogic'
import { NavPanelRecommendationAd } from './NavPanelRecommendationAd'

/** Give people a few days of real usage before nudging them about search - day-one users have nothing to search for yet. */
const CMD_K_AD_MIN_DAYS_SINCE_JOINING = 3

export function NavPanelAdvertisement(): JSX.Element | null {
    const logic = navPanelAdvertisementRecommendedLogic()
    const { oldestRecommendedProduct } = useValues(logic)
    const { activeCampaign } = useValues(navPanelProductPushLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const campaignFlagPayload = getFeatureFlagPayload('nav-panel-campaign') as CampaignPayload | undefined

    if (isLayoutNavCollapsed) {
        return null
    }

    // Cmd+K experiment arm takes the slot ahead of campaigns so exposure stays consistent for the analysis
    if (
        featureFlags[FEATURE_FLAGS.CMD_K_NAV_EXPERIMENT] === 'footer-callout' &&
        user?.date_joined &&
        dayjs().diff(dayjs(user.date_joined), 'day') >= CMD_K_AD_MIN_DAYS_SINCE_JOINING
    ) {
        return <NavPanelCmdKAd />
    }

    // Campaign flag payload takes priority over product recommendations, but campaigns promote cloud features so are not shown on hobby
    if (isCloudOrDev && isCampaignPayload(campaignFlagPayload)) {
        return <NavPanelCampaignAd campaign={campaignFlagPayload} />
    }

    // The org-wide product push campaign, driven by the growth backend. Respects the
    // user's "no product suggestions" setting.
    if (isCloudOrDev && activeCampaign && user?.allow_sidebar_suggestions !== false) {
        return <NavPanelProductPushAd campaign={activeCampaign} />
    }

    if (!oldestRecommendedProduct) {
        return null
    }

    return <NavPanelRecommendationAd recommendedProduct={oldestRecommendedProduct} />
}
