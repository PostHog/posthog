import { connect, kea, path, selectors } from 'kea'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { type UserProductListItem, UserProductListReason } from '~/queries/schema/schema-general'

import type { navPanelSalesLedLogicType } from './navPanelSalesLedLogicType'

export const navPanelSalesLedLogic = kea<navPanelSalesLedLogicType>([
    path(['lib', 'components', 'NavPanelAdvertisement', 'navPanelSalesLedLogic']),
    connect(() => ({
        values: [customProductsLogic, ['customProducts']],
        actions: [customProductsLogic, ['loadCustomProducts']],
    })),
    selectors({
        salesLedProducts: [
            (s) => [s.customProducts],
            (customProducts: UserProductListItem[]): UserProductListItem[] => {
                const fourteenDaysAgo = new Date()
                fourteenDaysAgo.setDate(fourteenDaysAgo.getDate() - 14)

                // Filter for sales-led items only, created in the last 14 days
                return customProducts.filter(
                    (item) =>
                        item.reason === UserProductListReason.SALES_LED &&
                        item.enabled &&
                        new Date(item.created_at) >= fourteenDaysAgo
                )
            },
        ],
        oldestSalesLedProduct: [
            (s) => [s.salesLedProducts],
            (salesLedProducts: UserProductListItem[]): UserProductListItem | null => {
                if (salesLedProducts.length === 0) {
                    return null
                }

                // Find the most recent sales-led product
                // Not using sort to make this more performant
                let oldestSalesLedProduct: UserProductListItem | null = null
                let oldestSalesLedProductDate: Date | null = null
                for (const product of salesLedProducts) {
                    const productDate = new Date(product.created_at)
                    if (!oldestSalesLedProductDate || productDate < oldestSalesLedProductDate) {
                        oldestSalesLedProduct = product
                        oldestSalesLedProductDate = productDate
                    }
                }

                return oldestSalesLedProduct
            },
        ],
    }),
])
