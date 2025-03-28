import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'
import { Currency, Revenue } from './RevenueExampleTableColumns'

const queryContext: QueryContext = {
    showOpenEditorButton: true,
    columns: {
        original_currency: {
            render: ({ value }) => {
                return <Currency currency={value as CurrencyCode} />
            },
        },
        original_revenue: {
            render: ({ value, record }) => {
                const originalCurrency = (record as any[])[3]
                return <Revenue value={value as number} currency={originalCurrency ?? CurrencyCode.USD} />
            },
        },
        currency: {
            render: ({ value }) => {
                return <Currency currency={value as CurrencyCode} />
            },
        },
        revenue: {
            render: ({ value, record }) => {
                const convertedCurrency = (record as any[])[5]
                return <Revenue value={value as number} currency={convertedCurrency ?? CurrencyCode.USD} />
            },
        },
    },
}

export function RevenueExampleEventsTable(): JSX.Element | null {
    const { exampleEventsQuery } = useValues(revenueEventsSettingsLogic)

    if (!exampleEventsQuery) {
        return null
    }

    return (
        <div>
            <h3>Revenue events</h3>
            <p>
                The following revenue events are available in your data. This is helpful when you're trying to debug
                what your revenue events look like.
            </p>

            <Query query={exampleEventsQuery} context={queryContext} />
        </div>
    )
}
