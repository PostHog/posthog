import { BindLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { Link } from '@posthog/lemon-ui'

import { addProductIntent } from 'lib/utils/product-intents'

import { getTreeItemsProducts } from '~/products'
import {
    FileSystemImport,
    ProductIntentContext,
    ProductKey,
    UserProductListItem,
    UserProductListReason,
} from '~/queries/schema/schema-general'

import { AdvertisementCard } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

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

export function NavPanelRecommendationAd({
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
                    <AdvertisementCard
                        emoji="✨"
                        emojiLabel="sparkles"
                        title={productInfo.displayLabel ?? productInfo.path}
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
