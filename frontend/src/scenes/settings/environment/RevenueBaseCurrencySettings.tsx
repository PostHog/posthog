import { useActions, useValues } from 'kea'
import { CurrencyDropdown } from 'products/revenue_analytics/frontend/settings/CurrencyDropdown'
import { revenueAnalyticsSettingsLogic } from 'products/revenue_analytics/frontend/settings/revenueAnalyticsSettingsLogic'

import { CurrencyCode } from '~/queries/schema/schema-general'

export function RevenueBaseCurrencySettings(): JSX.Element {
    const { baseCurrency } = useValues(revenueAnalyticsSettingsLogic)
    const { updateBaseCurrency, save } = useActions(revenueAnalyticsSettingsLogic)

    return (
        <div>
            <p>
                Posthog will convert all revenue values to this currency before displaying them to you. If we can't
                properly detect your revenue events' currency, we'll assume it's in this currency.
            </p>
            <CurrencyDropdown
                value={baseCurrency}
                onChange={(currency) => {
                    updateBaseCurrency(currency as CurrencyCode)
                    save()
                }}
            />
        </div>
    )
}
