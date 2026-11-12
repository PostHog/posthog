import { useActions, useValues } from 'kea'

import { IconHide, IconLightBulb } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { NAV_PANEL_PLACEMENT } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'
import {
    navPanelProductPushAdLogic,
    productPushDismissKey,
} from 'lib/components/NavPanelAdvertisement/navPanelProductPushAdLogic'
import { PRODUCT_PUSH_PROMPTS } from 'lib/components/NavPanelAdvertisement/productPushPrompts'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { TodayRow } from './TodayRow'
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
        <TodayRow
            tone="quiet"
            icon={PRODUCT_PUSH_ICON}
            title={prompt.title}
            facts={prompt.facts}
            to={destination}
            onOpen={() => reportAdClicked()}
            actions={
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="link-muted"
                                size="icon-sm"
                                aria-label="Don’t suggest this again"
                                onClick={() => {
                                    reportAdDismissed()
                                    hideAdvertisement()
                                }}
                                data-attr="today-product-push-hide"
                            />
                        }
                    >
                        <IconHide className="size-3.5" />
                    </TooltipTrigger>
                    <TooltipContent side="bottom">Don’t suggest this again</TooltipContent>
                </Tooltip>
            }
            dataAttr="today-product-push"
        />
    )
}
