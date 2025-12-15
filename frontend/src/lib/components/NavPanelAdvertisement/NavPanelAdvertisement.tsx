import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconX } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { addProductIntent } from 'lib/utils/product-intents'

import { pinnedFolderLogic } from '~/layout/panel-layout/PinnedFolder/pinnedFolderLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
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

export function NavPanelAdvertisement(): JSX.Element | null {
    const logic = navPanelAdvertisementRecommendedLogic()
    const { oldestRecommendedProduct } = useValues(logic)
    const { pinnedFolder } = useValues(pinnedFolderLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    // Only show when custom-products:// sidebar is active and not collapsed
    if (pinnedFolder !== 'custom-products://' || isLayoutNavCollapsed) {
        return null
    }

    if (!oldestRecommendedProduct) {
        return null
    }

    return <NavPanelAdvertisementContent recommendedProduct={oldestRecommendedProduct} />
}

export function NavPanelAdvertisementContent({
    recommendedProduct,
}: {
    recommendedProduct: UserProductListItem
}): JSX.Element | null {
    const allProducts = getTreeItemsProducts()
    const productInfo: FileSystemImport | undefined = allProducts.find(
        (p: FileSystemImport) => p.path === recommendedProduct.product_path
    )

    const logic = navPanelAdvertisementLogic({ productKey: recommendedProduct.product_path })
    const { hideAdvertisement } = useActions(logic)
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
                <div className="border rounded-sm bg-primary text-xs *:flex *:gap-2 *:px-2 *:py-1">
                    <div className="flex justify-between mt-1">
                        <div className="flex items-center gap-2">
                            <strong>
                                <span role="img" aria-label="sparkles">
                                    ✨
                                </span>{' '}
                                {productInfo.path}
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

                                posthog.capture('nav panel advertisement dismissed', {
                                    product_path: recommendedProduct.product_path,
                                    product_id: recommendedProduct.id,
                                })

                                hideAdvertisement()
                            }}
                            noPadding
                        />
                    </div>

                    <div className="flex flex-col gap-1">
                        <p className="mb-0">{getReasonText(recommendedProduct)}</p>
                    </div>
                </div>
            </Link>
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
