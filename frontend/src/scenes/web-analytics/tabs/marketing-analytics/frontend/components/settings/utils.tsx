// These are the currencies that are most important to show first because they're used by the most customers.

import { LemonSelectOption } from '@posthog/lemon-ui'
import {
    CURRENCY_SYMBOL_TO_EMOJI_MAP,
    CURRENCY_SYMBOL_TO_NAME_MAP,
    DISABLED_CURRENCIES,
} from 'lib/utils/geography/currency'

import { CurrencyCode } from '~/queries/schema/schema-general'

const optionFromCurrency = (currency: CurrencyCode): LemonSelectOption<CurrencyCode> => {
    return {
        value: currency,
        disabledReason: DISABLED_CURRENCIES[currency],
        label: (
            <span>
                {CURRENCY_SYMBOL_TO_EMOJI_MAP[currency]} {`${CURRENCY_SYMBOL_TO_NAME_MAP[currency]} (${currency})`}
            </span>
        ),
    }
}

const optionFromCurrencyAbbreviated = (currency: CurrencyCode): LemonSelectOption<CurrencyCode> => {
    return {
        value: currency,
        disabledReason: DISABLED_CURRENCIES[currency],
        label: (
            <span>
                {CURRENCY_SYMBOL_TO_EMOJI_MAP[currency]} {currency}
            </span>
        ),
    }
}

// Check our web analytics dashboard for the most popular countries from our visitors.
const IMPORTANT_CURRENCIES: CurrencyCode[] = [
    CurrencyCode.USD,
    CurrencyCode.EUR,
    CurrencyCode.GBP,
    CurrencyCode.CAD,
    CurrencyCode.INR,
    CurrencyCode.CNY,
    CurrencyCode.BRL,
]

// All the other currencies, sorted by their "long name" in alphabetical order.
const OTHER_CURRENCIES: CurrencyCode[] = (
    Object.keys(CurrencyCode).filter(
        (currency) => !IMPORTANT_CURRENCIES.includes(currency as CurrencyCode)
    ) as CurrencyCode[]
).sort((a, b) => {
    return CURRENCY_SYMBOL_TO_NAME_MAP[a].localeCompare(CURRENCY_SYMBOL_TO_NAME_MAP[b])
})

// Computing these before hand is more efficient than computing them on the fly.
export const OPTIONS_FOR_IMPORTANT_CURRENCIES: LemonSelectOption<CurrencyCode>[] =
    IMPORTANT_CURRENCIES.map(optionFromCurrency)
export const OPTIONS_FOR_OTHER_CURRENCIES: LemonSelectOption<CurrencyCode>[] = OTHER_CURRENCIES.map(optionFromCurrency)
export const OPTIONS_FOR_IMPORTANT_CURRENCIES_ABBREVIATED: LemonSelectOption<CurrencyCode>[] =
    IMPORTANT_CURRENCIES.map(optionFromCurrencyAbbreviated)
export const OPTIONS_FOR_OTHER_CURRENCIES_ABBREVIATED: LemonSelectOption<CurrencyCode>[] =
    OTHER_CURRENCIES.map(optionFromCurrencyAbbreviated)
