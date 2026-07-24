import { useValues } from 'kea'

import { IconReceipt } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyCurrency, humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingProductV2Type } from '~/types'

import { captureQuickstartAction } from './captureQuickstartAction'

export function UsageThisPeriod(): JSX.Element | null {
    const { isCloudOrDev } = useValues(preflightLogic)
    const { billing, canAccessBilling } = useValues(billingLogic)

    if (!isCloudOrDev || !canAccessBilling || !billing) {
        return null
    }

    const interval = billing.billing_period?.interval === 'year' ? 'year' : 'month'
    const eventsUsage = billing.products?.find(
        (product: BillingProductV2Type) => product.type === ProductKey.PRODUCT_ANALYTICS
    )?.current_usage

    let label: string | null = null
    if (billing.has_active_subscription && billing.current_total_amount_usd !== undefined) {
        label = `${humanFriendlyCurrency(billing.current_total_amount_usd)} this ${interval}`
    } else if (eventsUsage !== undefined) {
        // Free plans have no spend to show, but usage against the free tier is still meaningful
        label = `${humanFriendlyLargeNumber(eventsUsage)} events this ${interval}`
    }
    if (!label) {
        return null
    }

    return (
        <Link
            to={urls.organizationBilling()}
            onClick={() => captureQuickstartAction('view_billing_usage')}
            className="flex items-center gap-1 text-xs text-tertiary hover:text-primary"
            data-attr="quickstart-billing-usage"
        >
            <IconReceipt />
            <span>{label}</span>
        </Link>
    )
}
