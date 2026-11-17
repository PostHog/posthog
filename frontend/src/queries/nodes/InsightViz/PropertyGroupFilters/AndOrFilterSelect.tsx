import { LemonButtonProps, LemonSelect } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'

import { FilterLogicalOperator } from '~/types'

import { AND_OR_FILTER_OPTIONS, andOrFilterSuffix } from './andOrFilterOptions'
import { QuillAndOrFilterSelect } from './QuillAndOrFilterSelect'

export interface AndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    topLevelFilter?: boolean
    prefix?: React.ReactNode
    suffix?: [singular: string, plural: string]
    /** Shown instead of `suffix` in a narrow editor panel. Needs an `editor-panel` container ancestor */
    shortSuffix?: string
    disabledReason?: LemonButtonProps['disabledReason']
    size?: LemonButtonProps['size']
}

export function AndOrFilterSelect({
    onChange,
    value,
    topLevelFilter,
    prefix = 'Match',
    suffix = ['filter in this group', 'filters in this group'],
    shortSuffix,
    disabledReason,
    size = 'small',
}: AndOrFilterSelectProps): JSX.Element {
    const quillSurface = useQuillSurface()

    if (quillSurface) {
        return (
            <QuillAndOrFilterSelect
                onChange={onChange}
                value={value}
                prefix={prefix}
                suffix={suffix}
                shortSuffix={shortSuffix}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <div className="flex items-center font-medium">
            <span className="ml-2 @max-[410px]/editor-panel:ml-0">{prefix}</span>
            <LemonSelect
                className="mx-2"
                size={size}
                value={value}
                onChange={(type) => onChange(type as FilterLogicalOperator)}
                disabledReason={disabledReason}
                options={AND_OR_FILTER_OPTIONS.map((option) => ({
                    label: option.label,
                    value: option.value,
                    labelInMenu: (
                        <SelectOption<FilterLogicalOperator>
                            title={option.title}
                            description={option.description}
                            value={option.value}
                            selectedValue={value}
                        />
                    ),
                }))}
                optionTooltipPlacement={topLevelFilter ? 'bottom-end' : 'bottom-start'}
                dropdownMatchSelectWidth={false}
            />
            <span className={shortSuffix ? '@max-[375px]/editor-panel:hidden' : undefined}>
                {andOrFilterSuffix(value, suffix)}
            </span>
            {shortSuffix && <span className="hidden @max-[375px]/editor-panel:inline">{shortSuffix}</span>}
        </div>
    )
}

type SelectOptionProps<T extends React.ReactNode> = {
    title: string
    description: string
    value: T
    selectedValue: T
}

export const SelectOption = <T extends React.ReactNode>({
    title,
    description,
    value,
    selectedValue,
}: SelectOptionProps<T>): JSX.Element => (
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
