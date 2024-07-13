import { LemonButtonProps, LemonSelect } from '@posthog/lemon-ui'

import { FilterLogicalOperator } from '~/types'

interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    topLevelFilter?: boolean
    prefix?: React.ReactNode
    suffix?: [singular: string, plural: string]
    disabledReason?: LemonButtonProps['disabledReason']
}

export function AndOrFilterSelect({
    onChange,
    value,
    topLevelFilter,
    prefix = 'Match',
    suffix = ['filter in this group', 'filters in this group'],
    disabledReason,
}: AndOrFilterSelectProps): JSX.Element {
    return (
        <div className="flex items-center font-medium">
            <span className="ml-2">{prefix}</span>
            <LemonSelect
                className="mx-2"
                size="small"
                value={value}
                onChange={(type) => onChange(type as FilterLogicalOperator)}
                disabledReason={disabledReason}
                options={[
                    {
                        label: 'all',
                        value: FilterLogicalOperator.And,
                        labelInMenu: (
                            <SelectOption
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
                            <SelectOption
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

type SelectOptionProps = {
    title: string
    description: string
    value: FilterLogicalOperator
    selectedValue: FilterLogicalOperator
}

const SelectOption = ({ title, description, value, selectedValue }: SelectOptionProps): JSX.Element => (
    <div className="flex p-1 items-center">
        <div
            className={`flex shrink-0 font-bold w-10 h-10 mr-3 justify-center items-center rounded text-xs ${
                value === selectedValue ? 'bg-primary text-white' : 'bg-bg-3000 text-primary-alt'
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
