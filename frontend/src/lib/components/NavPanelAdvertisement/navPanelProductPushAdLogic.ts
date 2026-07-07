import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntent } from 'lib/utils/product-intents'

import { getTreeItemsProducts } from '~/products'
import { FileSystemImport, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import type { ProductPushDisplay } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import type { navPanelProductPushAdLogicType } from './navPanelProductPushAdLogicType'
import { getProductPushDisplay } from './navPanelProductPushDisplay'

export type NavPanelProductPushAdLogicProps = {
    campaign: ProductPushCampaignApi
}

// The dismiss state lives in the shared advertisement logic (its keyed instance also backs the
// card's dismiss button), so key it the same way here to read the same `hidden` flag.
const dismissKey = (campaign: ProductPushCampaignApi): string => `product-push-${campaign.id}`

export const navPanelProductPushAdLogic = kea<navPanelProductPushAdLogicType>([
    path(['lib', 'components', 'NavPanelAdvertisement', 'navPanelProductPushAdLogic']),
    props({} as NavPanelProductPushAdLogicProps),
    key(({ campaign }) => campaign.id),
    connect((props: NavPanelProductPushAdLogicProps) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            navPanelAdvertisementLogic({ campaign: dismissKey(props.campaign) }),
            ['hidden'],
        ],
    })),
    actions({
        reportAdShown: true,
        reportAdClicked: true,
        reportAdDismissed: true,
    }),
    selectors({
        productInfo: [
            () => [(_, props) => props.campaign],
            (campaign: ProductPushCampaignApi): FileSystemImport | undefined =>
                getTreeItemsProducts().find((p: FileSystemImport) => p.path === campaign.product_path),
        ],
        display: [
            () => [(_, props) => props.campaign],
            (campaign: ProductPushCampaignApi): ProductPushDisplay => getProductPushDisplay(campaign.product_key),
        ],
        // Never advertise a product this user can't open (mirrors the sidebar's flag filtering)
        flagGated: [
            (s) => [s.productInfo, s.featureFlags],
            (productInfo, featureFlags): boolean =>
                !!productInfo?.flag && !(featureFlags as Record<string, boolean>)[productInfo.flag],
        ],
        shouldRender: [
            (s) => [s.hidden, s.productInfo, s.flagGated],
            (hidden, productInfo, flagGated): boolean => !hidden && !!productInfo && !flagGated,
        ],
    }),
    listeners(({ props }) => ({
        reportAdShown: () => {
            posthog.capture('nav panel product push shown', {
                campaign_id: props.campaign.id,
                product_key: props.campaign.product_key,
            })
        },
        reportAdClicked: () => {
            posthog.capture('nav panel product push clicked', {
                campaign_id: props.campaign.id,
                product_key: props.campaign.product_key,
            })
            if (Object.values(ProductKey).includes(props.campaign.product_key as ProductKey)) {
                addProductIntent({
                    product_type: props.campaign.product_key as ProductKey,
                    intent_context: ProductIntentContext.NAV_PANEL_ADVERTISEMENT_CLICKED,
                    metadata: { campaign_id: props.campaign.id },
                })
            }
        },
        reportAdDismissed: () => {
            posthog.capture('nav panel product push dismissed', {
                campaign_id: props.campaign.id,
                product_key: props.campaign.product_key,
            })
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.shouldRender) {
            actions.reportAdShown()
        }
    }),
])
