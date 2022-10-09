import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import React from 'react'
import currencyMap from './currency-map.json'

// this is almost all possible just with `Intl` browser APIs but obvs not in IE and not yet in TS
// e.g. supported values of is not in TS yet
// see https://github.com/microsoft/TypeScript/issues/49231
// so instead steal this gist https://gist.githubusercontent.com/nhalstead/4c1652563dd13357ab936fc97703c019/raw/d5de097ef68f37501fb4d06030ca49f10f5f963a/currency-symbols.json

export type currencies = keyof typeof currencyMap

const options: LemonSelectMultipleOptionItem[] = Object.entries(currencyMap).map(
    ([abbreviation, { currency, symbol }]) => ({
        label: `${currency} (${abbreviation}) - ${symbol}`,
        key: abbreviation,
    })
)

export const isCurrency = (candidate: unknown): boolean => {
    return typeof candidate === 'string' && candidate in currencyMap
}

export const CurrencyPicker = ({
    value,
    onChange,
}: {
    value: string[]
    onChange: (currency: currencies) => void
}): JSX.Element => {
    return (
        <LemonSelectMultiple
            mode={'single'}
            options={options}
            onChange={(value: string[]): void => {
                onChange(value as currencies)
            }}
            value={value}
        />
    )
}
