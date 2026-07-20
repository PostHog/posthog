import { useValues } from 'kea'

import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { CampaignPayload, isCampaignPayload } from './navPanelAdShared'
import { navPanelAdvertisementRecommendedLogic } from './navPanelAdvertisementRecommendedLogic'
import { NavPanelCampaignAd } from './NavPanelCampaignAd'
import { NavPanelProductPushAd } from './NavPanelProductPushAd'
import { navPanelProductPushLogic } from './navPanelProductPushLogic'
import { NavPanelRecommendationAd } from './NavPanelRecommendationAd'

export function NavPanelAdvertisement(): JSX.Element | null {
    const logic = navPanelAdvertisementRecommendedLogic()
    const { oldestRecommendedProduct } = useValues(logic)
    const { activeCampaign } = useValues(navPanelProductPushLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { user } = useValues(userLogic)

    const campaignFlagPayload = getFeatureFlagPayload('nav-panel-campaign') as CampaignPayload | undefined

    if (isLayoutNavCollapsed) {
        return null
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
