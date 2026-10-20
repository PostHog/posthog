import { Text } from '@posthog/quill'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'

import { FilterLogicalOperator } from '~/types'

export interface QuillAndOrFilterSelectProps {
    value: FilterLogicalOperator
    onChange: (type: FilterLogicalOperator) => void
    prefix?: React.ReactNode
    suffix?: [singular: string, plural: string]
    /** Shown instead of `suffix` in a narrow editor panel. Needs an `editor-panel` container ancestor */
    shortSuffix?: string
    disabledReason?: React.ReactNode
}

export function QuillAndOrFilterSelect({
    value,
    onChange,
    prefix = 'Match',
    suffix = ['filter in this group', 'filters in this group'],
    shortSuffix,
    disabledReason,
}: QuillAndOrFilterSelectProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <Text size="xs" weight="medium" render={<span />} className="@max-[410px]/editor-panel:ml-0">
                {prefix}
            </Text>
            <QuillSelect<FilterLogicalOperator>
                className="w-auto"
                value={value}
                onChange={onChange}
                disabledReason={disabledReason}
                options={[
                    { value: FilterLogicalOperator.And, label: 'all', description: 'Every single filter must match' },
                    { value: FilterLogicalOperator.Or, label: 'any', description: 'One or more filters must match' },
                ]}
            />
            <Text
                size="xs"
                weight="medium"
                render={<span />}
                className={shortSuffix ? '@max-[375px]/editor-panel:hidden' : undefined}
            >
                {value === FilterLogicalOperator.Or ? suffix[0] : suffix[1]}
            </Text>
            {shortSuffix && (
                <Text size="xs" weight="medium" render={<span />} className="hidden @max-[375px]/editor-panel:inline">
                    {shortSuffix}
                </Text>
            )}
        </div>
    )
}
