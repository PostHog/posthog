import { LemonSelect } from '@posthog/lemon-ui'
import { FilterLogicalOperator } from '~/types'

interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    topLevelFilter?: boolean
    prefix?: React.ReactNode
    suffix?: React.ReactNode
}

export function AndOrFilterSelect({
    onChange,
    value,
    topLevelFilter,
    prefix = 'Match',
    suffix = 'filters in this group',
}: AndOrFilterSelectProps): JSX.Element {
    return (
        <div className="flex items-center font-medium">
            <span className="ml-2">{prefix}</span>
            <LemonSelect
                className="mx-2"
                size="small"
                value={value}
                onChange={(type) => onChange(type as FilterLogicalOperator)}
                options={[
                    {
                        label: 'all',
                        value: FilterLogicalOperator.And,
                        element: (
                            <SelectOption
                                title="All filter"
                                description="All filters must be met (logical and)"
                                value={FilterLogicalOperator.And}
                                selectedValue={value}
                            />
                        ),
                    },
                    {
                        label: 'any',
                        value: FilterLogicalOperator.Or,
                        element: (
                            <SelectOption
                                title="Any filter"
                                description="Any filter can be met (logical or)"
                                value={FilterLogicalOperator.Or}
                                selectedValue={value}
                            />
                        ),
                    },
                ]}
                optionTooltipPlacement={topLevelFilter ? 'bottomRight' : 'bottomLeft'}
            />
            {suffix}
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
    <div className="flex p-2 items-center">
        <div
            className={`flex font-bold w-10 h-10 mr-3 justify-center items-center rounded text-xs ${
                value === selectedValue ? 'bg-primary text-white' : 'bg-mid text-primary-alt'
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
