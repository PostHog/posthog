import { useActions, useValues } from 'kea'
import { CurrencyDropdown } from 'scenes/data-management/revenue/CurrencyDropdown'
import { revenueEventsSettingsLogic } from 'scenes/data-management/revenue/revenueEventsSettingsLogic'

import { CurrencyCode } from '~/queries/schema/schema-general'

export function RevenueBaseCurrencySettings(): JSX.Element {
    const { baseCurrency } = useValues(revenueEventsSettingsLogic)
    const { updateBaseCurrency, save } = useActions(revenueEventsSettingsLogic)

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
