import { LemonButtonProps, LemonSelect } from '@posthog/lemon-ui'

import { FilterLogicalOperator } from '~/types'

interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    topLevelFilter?: boolean
    prefix?: React.ReactNode
    suffix?: [singular: string, plural: string]
    disabledReason?: LemonButtonProps['disabledReason']
    size?: LemonButtonProps['size']
}

export function AndOrFilterSelect({
    onChange,
    value,
    topLevelFilter,
    prefix = 'Match',
    suffix = ['filter in this group', 'filters in this group'],
    disabledReason,
    size = 'small',
}: AndOrFilterSelectProps): JSX.Element {
    return (
        <div className="flex items-center font-medium">
            <span className="ml-2">{prefix}</span>
            <LemonSelect
                className="mx-2"
                size={size}
                value={value}
                onChange={(type) => onChange(type as FilterLogicalOperator)}
                disabledReason={disabledReason}
                options={[
                    {
                        label: 'all',
                        value: FilterLogicalOperator.And,
                        labelInMenu: (
                            <SelectOption<FilterLogicalOperator>
                                title="All"
                                description="Every single filter must match"
                                value={FilterLogicalOperator.And}
                                selectedValue={value}
                            />
                        ),
                    },
                    {
                        label: 'any',
                        value: FilterLogicalOperator.Or,
                        labelInMenu: (
                            <SelectOption<FilterLogicalOperator>
                                title="Any"
                                description="One or more filters must match"
                                value={FilterLogicalOperator.Or}
                                selectedValue={value}
                            />
                        ),
                    },
                ]}
                optionTooltipPlacement={topLevelFilter ? 'bottom-end' : 'bottom-start'}
                dropdownMatchSelectWidth={false}
            />
            {value === FilterLogicalOperator.Or ? suffix[0] : suffix[1]}
        </div>
    )
}

type SelectOptionProps<T> = {
    title: string
    description: string
    value: T
    selectedValue: T
}

export const SelectOption = <T,>({ title, description, value, selectedValue }: SelectOptionProps<T>): JSX.Element => (
    <div className="flex p-1 items-center">
        <div
            className={`flex shrink-0 font-bold w-10 h-10 mr-3 justify-center items-center rounded text-xs ${
                value === selectedValue
                    ? 'bg-accent text-primary-inverse [text-shadow:0_0_1px_black]'
                    : 'bg-surface-secondary text-primary'
            }`}
        >
            {value}
        </div>
        <div>
            <div className="font-bold">{title}</div>
            <div className="font-normal">{description}</div>
        </div>
    </div>
)
