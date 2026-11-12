import { useActions, useValues } from 'kea'

import { IconLightBulb } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { NAV_PANEL_PLACEMENT } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'
import {
    navPanelProductPushAdLogic,
    productPushDismissKey,
} from 'lib/components/NavPanelAdvertisement/navPanelProductPushAdLogic'
import { PRODUCT_PUSH_PROMPTS } from 'lib/components/NavPanelAdvertisement/productPushPrompts'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { isExternalLink } from 'lib/utils/url'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { TodayPromptItem } from './TodayPromptItem'
import type { TodayRowIcon } from './todayRowIcons'

const PRODUCT_PUSH_ICON: TodayRowIcon = {
    color: 'var(--color-product-early-access-features-light)',
    glyph: <IconLightBulb />,
}

export function TodayProductPushRow({ campaign }: { campaign: ProductPushCampaignApi }): JSX.Element | null {
    const logic = navPanelProductPushAdLogic({ campaign, placement: NAV_PANEL_PLACEMENT.TODAY_HOME })
    const { shouldRender, destination } = useValues(logic)
    const { reportAdClicked, reportAdDismissed } = useActions(logic)
    const { hideAdvertisement } = useActions(
        navPanelAdvertisementLogic({ dismissKey: productPushDismissKey(campaign) })
    )
    const prompt = PRODUCT_PUSH_PROMPTS[campaign.product_key]

    if (!shouldRender || !destination || !prompt) {
        return null
    }

    return (
        <TodayPromptItem
            icon={PRODUCT_PUSH_ICON}
            title={prompt.title}
            meta={prompt.description}
            dataAttr="today-product-push"
            actions={
                <>
                    <Button
                        size="sm"
                        variant="link-muted"
                        onClick={() => {
                            reportAdDismissed()
                            hideAdvertisement()
                        }}
                        data-attr="today-product-push-hide"
                    >
                        Not now
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        render={
                            <LinkPrimitive
                                to={destination}
                                target={isExternalLink(destination) ? '_blank' : undefined}
                            />
                        }
                        onClick={() => reportAdClicked()}
                        data-attr="today-product-push-open"
                    >
                        {prompt.action}
                    </Button>
                </>
            }
        />
    )
}
