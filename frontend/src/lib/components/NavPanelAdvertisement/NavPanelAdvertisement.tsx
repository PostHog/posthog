import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconX } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { addProductIntent } from 'lib/utils/product-intents'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { pinnedFolderLogic } from '~/layout/panel-layout/PinnedFolder/pinnedFolderLogic'
import { getTreeItemsProducts } from '~/products'
import {
    FileSystemImport,
    ProductIntentContext,
    ProductKey,
    UserProductListItem,
    UserProductListReason,
} from '~/queries/schema/schema-general'

import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { navPanelAdvertisementRecommendedLogic } from './navPanelAdvertisementRecommendedLogic'

interface CampaignPayload {
    campaign: string
    text: string
    emoji: string
    emojiLabel: string
    title: string
}

function isCampaignPayload(value: unknown): value is CampaignPayload {
    return (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as CampaignPayload).campaign === 'string' &&
        typeof (value as CampaignPayload).text === 'string' &&
        typeof (value as CampaignPayload).emoji === 'string' &&
        typeof (value as CampaignPayload).emojiLabel === 'string' &&
        typeof (value as CampaignPayload).title === 'string'
    )
}

export function NavPanelAdvertisement(): JSX.Element | null {
    const logic = navPanelAdvertisementRecommendedLogic()
    const { oldestRecommendedProduct } = useValues(logic)
    const { pinnedFolder } = useValues(pinnedFolderLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    const isAIFirst = useFeatureFlag('AI_FIRST')
    const campaignFlagPayload = getFeatureFlagPayload('nav-panel-campaign') as CampaignPayload | undefined

    if (isLayoutNavCollapsed) {
        return null
    }

    // Show when custom-products sidebar is active (old sidebar) or AI-first sidebar is enabled
    if (!isAIFirst && pinnedFolder !== 'custom-products://') {
        return null
    }

    // Campaign flag payload takes priority over product recommendations
    if (isCampaignPayload(campaignFlagPayload)) {
        return <NavPanelCampaignContent campaign={campaignFlagPayload} />
    }

    if (!oldestRecommendedProduct) {
        return null
    }

    return <NavPanelAdvertisementContent recommendedProduct={oldestRecommendedProduct} />
}

function NavPanelCampaignContent({ campaign }: { campaign: CampaignPayload }): JSX.Element | null {
    const logicProps = { campaign: `campaign-${campaign.campaign}` }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)

    useEffect(() => {
        if (!hidden) {
            posthog.capture('nav panel campaign shown', { campaign: campaign.campaign })
        }
    }, [campaign.campaign, hidden])

    if (hidden) {
        return null
    }

    return (
        <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
            <Content
                emoji={campaign.emoji}
                emojiLabel={campaign.emojiLabel}
                title={campaign.title}
                text={campaign.text}
                onClose={() => {
                    posthog.capture('nav panel campaign dismissed', {
                        campaign: campaign.campaign,
                    })
                }}
            />
        </BindLogic>
    )
}

function NavPanelAdvertisementContent({
    recommendedProduct,
}: {
    recommendedProduct: UserProductListItem
}): JSX.Element | null {
    const allProducts = getTreeItemsProducts()
    const productInfo: FileSystemImport | undefined = allProducts.find(
        (p: FileSystemImport) => p.path === recommendedProduct.product_path
    )

    const logicProps = { campaign: recommendedProduct.product_path }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)

    useEffect(() => {
        if (!hidden && productInfo) {
            posthog.capture('nav panel advertisement shown', {
                product_path: recommendedProduct.product_path,
                product_id: recommendedProduct.id,
            })
        }
    }, [recommendedProduct.product_path, recommendedProduct.id, productInfo, hidden])

    const reasonText = getReasonText(recommendedProduct)
    if (hidden || !productInfo || !reasonText) {
        return null
    }

    return (
        <div className="w-full">
            <Link
                to={productInfo.href}
                className="text-primary"
                onClick={() => {
                    posthog.capture('nav panel advertisement clicked', {
                        product_path: recommendedProduct.product_path,
                        product_id: recommendedProduct.id,
                    })
                    if (productInfo.intents && productInfo.intents.length > 0) {
                        const productKey = productInfo.intents[0]
                        if (productKey in ProductKey) {
                            addProductIntent({
                                product_type: productKey as ProductKey,
                                intent_context: ProductIntentContext.NAV_PANEL_ADVERTISEMENT_CLICKED,
                                metadata: { product_path: recommendedProduct.product_path },
                            })
                        }
                    }
                }}
            >
                <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
                    <Content
                        emoji="✨"
                        emojiLabel="sparkles"
                        title={productInfo.path}
                        text={getReasonText(recommendedProduct) ?? ''}
                        onClose={() => {
                            posthog.capture('nav panel advertisement dismissed', {
                                product_path: recommendedProduct.product_path,
                                product_id: recommendedProduct.id,
                            })
                        }}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}

function Content({
    emoji,
    emojiLabel,
    title,
    text,
    onClose,
}: {
    emoji: string
    emojiLabel: string
    title: string
    text: string
    onClose?: () => void
}): JSX.Element {
    const { hideAdvertisement } = useActions(navPanelAdvertisementLogic)

    return (
        <div className="border rounded-sm bg-primary text-xs *:flex *:gap-2 *:px-2 *:py-1">
            <div className="flex justify-between">
                <div className="flex items-center gap-2">
                    <strong>
                        <span role="img" aria-label={emojiLabel}>
                            {emoji}
                        </span>{' '}
                        {title}
                    </strong>
                </div>
                <LemonButton
                    icon={<IconX className="text-muted m-1" />}
                    tooltip="Dismiss"
                    tooltipPlacement="right"
                    size="xxsmall"
                    onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()

                        onClose?.()

                        hideAdvertisement()
                    }}
                    noPadding
                />
            </div>

            <div className="flex flex-col gap-1">
                <p className="mb-0" dangerouslySetInnerHTML={{ __html: text }} />
            </div>
        </div>
    )
}

const getReasonText = (product: UserProductListItem): string | null => {
    if (product.reason_text) {
        return product.reason_text
    }

    switch (product.reason) {
        case UserProductListReason.SALES_LED:
            return "We've added this product to your sidebar because we believe you'd benefit from it! Your TAM will reach out to help you learn more about it."
        case UserProductListReason.NEW_PRODUCT:
            return "We've just released this new product. Based on your usage, we believe you'll like it. Give it a try!"
    }

    return null
}
