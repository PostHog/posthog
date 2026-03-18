import { connect, kea, path, selectors } from 'kea'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { type UserProductListItem, UserProductListReason } from '~/queries/schema/schema-general'

import type { navPanelAdvertisementRecommendedLogicType } from './navPanelAdvertisementRecommendedLogicType'

const RECOMMENDED_PRODUCT_CREATED_AT_THRESHOLD_IN_DAYS = 7
const RECOMMENDED_PRODUCT_REASONS: UserProductListReason[] = [
    UserProductListReason.SALES_LED,
    UserProductListReason.NEW_PRODUCT,
]

export const navPanelAdvertisementRecommendedLogic = kea<navPanelAdvertisementRecommendedLogicType>([
    path(['lib', 'components', 'NavPanelAdvertisement', 'navPanelAdvertisementRecommendedLogic']),
    connect(() => ({
        values: [customProductsLogic, ['customProducts']],
    })),
    selectors({
        recommendedProducts: [
            (s) => [s.customProducts],
            (customProducts: UserProductListItem[]): UserProductListItem[] => {
                const createdAtThreshold = new Date()
                createdAtThreshold.setDate(
                    createdAtThreshold.getDate() - RECOMMENDED_PRODUCT_CREATED_AT_THRESHOLD_IN_DAYS
                )

                // Filter for the items we care about recommending in the ad slot, created in the last 7 days
                return customProducts.filter(
                    (item) =>
                        RECOMMENDED_PRODUCT_REASONS.includes(item.reason) &&
                        item.enabled &&
                        new Date(item.created_at) >= createdAtThreshold
                )
            },
        ],
        oldestRecommendedProduct: [
            (s) => [s.recommendedProducts],
            (recommendedProducts: UserProductListItem[]): UserProductListItem | null => {
                if (recommendedProducts.length === 0) {
                    return null
                }

                // Find the oldest recommended product
                // Not using sort to make this more performant, where's TS' stdlib when you need it?
                let oldestRecommendedProduct: UserProductListItem | null = null
                let oldestRecommendedProductDate: Date | null = null
                for (const product of recommendedProducts) {
                    const productDate = new Date(product.created_at)
                    if (!oldestRecommendedProductDate || productDate < oldestRecommendedProductDate) {
                        oldestRecommendedProduct = product
                        oldestRecommendedProductDate = productDate
                    }
                }

                return oldestRecommendedProduct
            },
        ],
    }),
])
