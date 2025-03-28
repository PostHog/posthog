import { useValues } from 'kea'
import { CURRENCY_SYMBOL_TO_EMOJI_MAP } from 'lib/utils/geography/currency'
import { getCurrencySymbol } from 'lib/utils/geography/currency'

import { Query } from '~/queries/Query/Query'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { QueryContextColumn } from '~/queries/types'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

const Revenue = ({ value, currency }: { value: number; currency: string }): JSX.Element => {
    const { symbol, isPrefix } = getCurrencySymbol(currency ?? CurrencyCode.USD)
    return <div>{`${isPrefix ? symbol : ''}${value.toLocaleString()}${isPrefix ? '' : ' ' + symbol}`}</div>
}

const Currency = ({ currency }: { currency: string }): JSX.Element => {
    return (
        <div>
            {CURRENCY_SYMBOL_TO_EMOJI_MAP[currency as CurrencyCode]} {currency}
        </div>
    )
}

const COLUMNS: Record<string, QueryContextColumn> = {
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
}

export function RevenueExampleDataWarehouseTablesData(): JSX.Element | null {
    const { exampleDataWarehouseTablesQuery } = useValues(revenueEventsSettingsLogic)

    if (!exampleDataWarehouseTablesQuery) {
        return null
    }

    return (
        <div>
            <h3>Data warehouse tables revenue data</h3>
            <p>
                The following rows of data were imported from your data warehouse tables. This is helpful when you're
                trying to debug what your revenue data looks like.
            </p>
            <Query query={exampleDataWarehouseTablesQuery} context={{ showOpenEditorButton: true, columns: COLUMNS }} />
        </div>
    )
}
