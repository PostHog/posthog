/**
 * The billing service owns `name`, so a product can be billed under a name the app stopped using.
 * Override it here, keyed by product type, so billing calls a product what the rest of PostHog
 * calls it — otherwise people search billing for a product they can see in the nav and miss it.
 */
const DISPLAY_NAME_BY_PRODUCT_TYPE: Record<string, string> = {
    realtime_destinations: 'Data pipelines',
    workflows_emails: 'Workflows',
    inbox: 'Self-driving inbox',
}

export function billingProductDisplayName(product: { type?: string | null; name: string }): string {
    return (product.type && DISPLAY_NAME_BY_PRODUCT_TYPE[product.type]) || product.name
}
