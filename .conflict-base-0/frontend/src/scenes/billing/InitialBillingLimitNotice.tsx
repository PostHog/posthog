import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, ProductKey } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

const InitialBillingLimitNoticeContents = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { currentAndUpgradePlans, hasCustomLimitSet, customLimitUsd } = useValues(billingProductLogic({ product }))
    const initialBillingLimit = currentAndUpgradePlans?.currentPlan?.initial_billing_limit
    const isUsingInitialBillingLimit =
        hasCustomLimitSet && currentAndUpgradePlans?.currentPlan?.initial_billing_limit == customLimitUsd

    return isUsingInitialBillingLimit ? (
        <LemonBanner
            type="info"
            className="my-4"
            action={{
                type: 'primary',
                children: 'Change limit',
                to: urls.organizationBilling([product.type as ProductKey]),
            }}
            dismissKey={`initial-billing-limit-notice-${product.type}`}
        >
            <p className="flex-1 min-w-full sm:min-w-0">
                Default initial billing limit of <b className="text-accent">${initialBillingLimit}</b> active.
            </p>
            <p className="font-normal">
                This protects you from accidentally incurring large unexpected charges. Some features may stop working
                and data may be dropped if your usage exceeds your limit.
            </p>
        </LemonBanner>
    ) : null
}

export const InitialBillingLimitNotice = ({ product_key }: { product_key: ProductKey }): JSX.Element | null => {
    const { billing } = useValues(billingLogic)
    const product = billing?.products.find((p) => p.type === product_key)
    return product ? <InitialBillingLimitNoticeContents product={product} /> : null
}
