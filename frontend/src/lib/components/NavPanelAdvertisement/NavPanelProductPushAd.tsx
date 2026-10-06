import { BindLogic, useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { isExternalLink } from 'lib/utils/url'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { AdvertisementCard } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { navPanelProductPushAdLogic } from './navPanelProductPushAdLogic'

export function NavPanelProductPushAd({ campaign }: { campaign: ProductPushCampaignApi }): JSX.Element | null {
    const logic = navPanelProductPushAdLogic({ campaign })
    const { display, shouldRender, destination, label } = useValues(logic)
    const { reportAdClicked, reportAdDismissed } = useActions(logic)

    if (!shouldRender || !destination) {
        return null
    }

    return (
        <div className="w-full">
            <Link
                to={destination}
                target={isExternalLink(destination) ? '_blank' : undefined}
                className="text-primary"
                onClick={() => reportAdClicked()}
            >
                <BindLogic logic={navPanelAdvertisementLogic} props={{ dismissKey: `product-push-${campaign.id}` }}>
                    <AdvertisementCard
                        title={label ?? ''}
                        text={campaign.reason_text || display.tagline}
                        hero={display}
                        onClose={() => reportAdDismissed()}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}
