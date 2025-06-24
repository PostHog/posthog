import { LemonSelect, LemonSelectProps } from '@posthog/lemon-ui'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { OPTIONS_FOR_IMPORTANT_CURRENCIES, OPTIONS_FOR_OTHER_CURRENCIES } from './utils'

type CurrencyDropdownProps = {
    value: CurrencyCode | null
    onChange: (currency: CurrencyCode | null) => void
    size?: LemonSelectProps<any>['size']
    visible?: boolean // Useful for stories to display the dropdown content
}

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
