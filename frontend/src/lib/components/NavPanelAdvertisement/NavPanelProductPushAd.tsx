import { BindLogic, useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { AdvertisementCard } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { navPanelProductPushAdLogic } from './navPanelProductPushAdLogic'

export function NavPanelProductPushAd({ campaign }: { campaign: ProductPushCampaignApi }): JSX.Element | null {
    const logic = navPanelProductPushAdLogic({ campaign })
    const { productInfo, display, shouldRender } = useValues(logic)
    const { reportAdClicked, reportAdDismissed } = useActions(logic)

    if (!shouldRender || !productInfo) {
        return null
    }

    return (
        <div className="w-full">
            <Link to={productInfo.href} className="text-primary" onClick={() => reportAdClicked()}>
                <BindLogic logic={navPanelAdvertisementLogic} props={{ campaign: `product-push-${campaign.id}` }}>
                    <AdvertisementCard
                        title={productInfo.displayLabel ?? productInfo.path}
                        text={campaign.reason_text || display.tagline}
                        hero={display}
                        onClose={() => reportAdDismissed()}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}
