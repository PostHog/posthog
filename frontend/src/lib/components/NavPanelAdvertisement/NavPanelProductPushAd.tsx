import { BindLogic, useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { isExternalLink } from 'lib/utils/url'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { AdvertisementCard, NAV_PANEL_CARD_TYPE, NavPanelSlot, SIDEBAR_SLOT } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { navPanelProductPushAdLogic, productPushDismissKey } from './navPanelProductPushAdLogic'

export function NavPanelProductPushAd({
    campaign,
    slot = SIDEBAR_SLOT,
}: {
    campaign: ProductPushCampaignApi
    slot?: NavPanelSlot
}): JSX.Element | null {
    const logic = navPanelProductPushAdLogic({ campaign, placement: slot.placement })
    const { display, shouldRender, destination, label } = useValues(logic)
    const { reportAdClicked, reportAdDismissed } = useActions(logic)

    if (!shouldRender || !destination) {
        return null
    }

    const dismissKey = productPushDismissKey(campaign)

    return slot.frame(
        <Link
            to={destination}
            target={isExternalLink(destination) ? '_blank' : undefined}
            className="text-primary"
            onClick={() => reportAdClicked()}
        >
            <BindLogic logic={navPanelAdvertisementLogic} props={{ dismissKey }}>
                <AdvertisementCard
                    title={label ?? ''}
                    text={campaign.reason_text || display.tagline}
                    hero={display}
                    onClose={() => reportAdDismissed()}
                />
            </BindLogic>
        </Link>,
        { id: dismissKey, cardType: NAV_PANEL_CARD_TYPE.PRODUCT_PUSH, title: label ?? '', Hoggie: display.Hoggie }
    )
}
