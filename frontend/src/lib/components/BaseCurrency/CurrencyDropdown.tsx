import { LemonSelect, LemonSelectOption, LemonSelectProps } from '@posthog/lemon-ui'
import {
    CURRENCY_SYMBOL_TO_EMOJI_MAP,
    CURRENCY_SYMBOL_TO_NAME_MAP,
    DISABLED_CURRENCIES,
} from 'lib/utils/geography/currency'

import { CurrencyCode } from '~/queries/schema/schema-general'

type CurrencyDropdownProps = {
    value: CurrencyCode | null
    onChange: (currency: CurrencyCode | null) => void
    size?: LemonSelectProps<any>['size']
    visible?: boolean // Useful for stories to display the dropdown content
}

// These are the currencies that are most important to show first because they're used by the most customers.
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

const optionFromCurrency = (currency: CurrencyCode): LemonSelectOption<CurrencyCode> => {
    return {
        value: currency,
        disabledReason: DISABLED_CURRENCIES[currency],
        label: (
            <span>
                {CURRENCY_SYMBOL_TO_EMOJI_MAP[currency]} {CURRENCY_SYMBOL_TO_NAME_MAP[currency]} ({currency})
            </span>
        ),
    }
}

// Computing these before hand is more efficient than computing them on the fly.
const OPTIONS_FOR_IMPORTANT_CURRENCIES: LemonSelectOption<CurrencyCode>[] = IMPORTANT_CURRENCIES.map(optionFromCurrency)
const OPTIONS_FOR_OTHER_CURRENCIES: LemonSelectOption<CurrencyCode>[] = OTHER_CURRENCIES.map(optionFromCurrency)

export const CurrencyDropdown = ({ value, onChange, visible, size }: CurrencyDropdownProps): JSX.Element => {
    return (
        <LemonSelect
            visible={visible}
            value={value}
            onChange={(newValue) => onChange(newValue as CurrencyCode | null)}
            options={[
                { options: OPTIONS_FOR_IMPORTANT_CURRENCIES, title: 'Most Popular' },
                { options: OPTIONS_FOR_OTHER_CURRENCIES, title: 'Other currencies' },
            ]}
            size={size}
        />
    )
}
