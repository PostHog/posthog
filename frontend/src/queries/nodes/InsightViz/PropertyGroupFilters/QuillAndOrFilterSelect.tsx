import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { FilterLogicalOperator } from '~/types'

import { AND_OR_FILTER_OPTIONS, andOrFilterSuffix } from './andOrFilterOptions'

export interface QuillAndOrFilterSelectProps {
    onChange: (type: FilterLogicalOperator) => void
    value: FilterLogicalOperator
    prefix: React.ReactNode
    suffix: [singular: string, plural: string]
    shortSuffix?: string
    disabledReason?: React.ReactNode
}

export function QuillAndOrFilterSelect({
    onChange,
    value,
    prefix,
    suffix,
    shortSuffix,
    disabledReason,
}: QuillAndOrFilterSelectProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-medium">
            <span>{prefix}</span>
            <Select<FilterLogicalOperator>
                value={value}
                onValueChange={(next: FilterLogicalOperator | null) => next !== null && onChange(next)}
                disabled={!!disabledReason}
            >
                <SelectTrigger render={<Button variant="outline" left disabledReason={disabledReason || undefined} />}>
                    <SelectValue>
                        {(selected: FilterLogicalOperator) =>
                            AND_OR_FILTER_OPTIONS.find((option) => option.value === selected)?.label ?? selected
                        }
                    </SelectValue>
                </SelectTrigger>
                <SelectContent align="start" alignItemWithTrigger={false}>
                    {AND_OR_FILTER_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            <span className="flex flex-col">
                                <span>{option.title}</span>
                                <Text size="xs" variant="muted" render={<span />}>
                                    {option.description}
                                </Text>
                            </span>
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <span className={shortSuffix ? '@max-sm/editor-panel:hidden' : undefined}>
                {andOrFilterSuffix(value, suffix)}
            </span>
            {shortSuffix && <span className="hidden @max-sm/editor-panel:inline">{shortSuffix}</span>}
        </div>
    )
}
