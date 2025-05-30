import { useActions, useValues } from 'kea'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { CurrencyDropdown } from './CurrencyDropdown'

export function BaseCurrency(): JSX.Element {
    const { baseCurrency } = useValues(marketingAnalyticsSettingsLogic)
    const { updateBaseCurrency } = useActions(marketingAnalyticsSettingsLogic)

    return (
        <div>
            <h3>Base currency</h3>
            <p>
                PostHog will convert all marketing analytics values to this currency before displaying them to you. If
                we can't properly detect your marketing analytics' currency, we'll assume it's in this currency as well.
            </p>
            <CurrencyDropdown
                value={baseCurrency}
                onChange={(currency) => {
                    updateBaseCurrency(currency as CurrencyCode)
                }}
            />
        </div>
    )
}
