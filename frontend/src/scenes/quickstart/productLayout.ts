import { ProductKey } from '~/queries/schema/schema-general'

export interface QuickstartProductLayoutConfig {
    featured: {
        title: string
        description: string
        productKeys: ProductKey[]
    }
    additional: {
        title: string
        description: string
    }
}

export const QUICKSTART_PRODUCT_ORDER: ProductKey[] = [
    ProductKey.PRODUCT_ANALYTICS,
    ProductKey.WEB_ANALYTICS,
    ProductKey.SESSION_REPLAY,
    ProductKey.ERROR_TRACKING,
    ProductKey.FEATURE_FLAGS,
    ProductKey.SURVEYS,
    ProductKey.EXPERIMENTS,
    ProductKey.AI_OBSERVABILITY,
    ProductKey.DATA_WAREHOUSE,
    ProductKey.WORKFLOWS,
    ProductKey.LOGS,
    ProductKey.MCP_ANALYTICS,
    ProductKey.CONVERSATIONS,
]

export const QUICKSTART_PRODUCT_LAYOUT: QuickstartProductLayoutConfig = {
    featured: {
        title: 'Your tools',
        description: 'Focus on the products that matter most to you right now.',
        productKeys: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.FEATURE_FLAGS],
    },
    additional: {
        title: 'Explore more tools',
        description: 'Add another product when it becomes relevant to your work.',
    },
}

export type QuickstartFeaturedProductOverrides = Partial<Record<ProductKey, boolean>>

export function isQuickstartProductFeatured(
    productKey: ProductKey,
    overrides: QuickstartFeaturedProductOverrides
): boolean {
    return overrides[productKey] ?? QUICKSTART_PRODUCT_LAYOUT.featured.productKeys.includes(productKey)
}

export function getQuickstartProductSections<T extends { key: ProductKey }>(
    products: T[],
    overrides: QuickstartFeaturedProductOverrides
): { featuredProducts: T[]; additionalProducts: T[] } {
    const featuredProducts: T[] = []
    const additionalProducts: T[] = []

    for (const product of products) {
        if (isQuickstartProductFeatured(product.key, overrides)) {
            featuredProducts.push(product)
        } else {
            additionalProducts.push(product)
        }
    }

    return { featuredProducts, additionalProducts }
}
