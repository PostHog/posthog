import { LemonSelect, LemonSelectOption, LemonSelectProps } from '@posthog/lemon-ui'
import {
    CURRENCY_SYMBOL_TO_EMOJI_MAP,
    CURRENCY_SYMBOL_TO_NAME_MAP,
    DISABLED_CURRENCIES,
} from 'lib/utils/geography/currency'
import React from 'react'

import { CurrencyCode } from '~/queries/schema/schema-general'

type T = CurrencyCode | null
type SelectProps = LemonSelectProps<T>
type SelectOption = LemonSelectOption<T>
type CurrencyDropdownProps = Omit<SelectProps, 'options'>

export const CurrencyDropdown: React.FC<CurrencyDropdownProps> = (props) => {
    return (
        <LemonSelect
            {...props}
            options={
                Object.keys(CurrencyCode).map((currency) => {
                    const mappedCurrency = currency as CurrencyCode // Make TS happy, can't type on the function signature

                    return {
                        value: mappedCurrency,
                        disabledReason: DISABLED_CURRENCIES[mappedCurrency],
                        label: (
                            <span>
                                {CURRENCY_SYMBOL_TO_EMOJI_MAP[mappedCurrency]}{' '}
                                {CURRENCY_SYMBOL_TO_NAME_MAP[mappedCurrency]}
                            </span>
                        ),
                    }
                }) as SelectOption[]
            }
        />
    )
}
