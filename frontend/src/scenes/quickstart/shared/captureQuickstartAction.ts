import posthog from 'posthog-js'

import { isAuthenticatedTeam } from 'scenes/teamLogic'

import { getQuickstartTrackingProperties, quickstartLogic } from '../quickstartLogic'

export function captureQuickstartAction(
    action: string,
    productKey?: string,
    properties?: Record<string, unknown>
): void {
    const quickstartValues = quickstartLogic.findMounted()?.values
    const currentTeam = quickstartValues?.currentTeam
    const products = quickstartValues?.products ?? []
    const product = productKey ? products.find((candidate) => candidate.key === productKey) : undefined
    const trackingProperties = isAuthenticatedTeam(currentTeam)
        ? getQuickstartTrackingProperties(currentTeam, products)
        : {}
    const onboardedProducts = new Set(
        Array.isArray(trackingProperties.onboarded_products) ? trackingProperties.onboarded_products : []
    )
    const isCrossSell =
        !!product &&
        trackingProperties.is_post_onboarding === true &&
        !onboardedProducts.has(product.key) &&
        product.status.level !== 'live'

    posthog.capture('quickstart action clicked', {
        ...trackingProperties,
        action,
        ...(productKey ? { product_key: productKey } : {}),
        ...(product
            ? {
                  product_status: product.status.level,
                  product_was_onboarded: onboardedProducts.has(product.key),
                  is_cross_sell: isCrossSell,
              }
            : {}),
        ...properties,
    })
}
