import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import React from 'react'
import currencyMap from './currency-map.json'

// currencies stolen from this gist https://gist.githubusercontent.com/nhalstead/4c1652563dd13357ab936fc97703c019/raw/d5de097ef68f37501fb4d06030ca49f10f5f963a/currency-symbols.json

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
    value: currencies
    onChange: (currency: currencies) => void
}): JSX.Element => {
    return (
        <LemonSelectMultiple
            mode={'single'}
            options={options}
            onChange={(value: string[]): void => {
                onChange(value as unknown as currencies)
            }}
            value={value as unknown as string[]}
        />
    )
}
