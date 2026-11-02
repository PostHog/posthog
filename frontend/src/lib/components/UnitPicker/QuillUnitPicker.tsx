import { ReactNode } from 'react'

import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    SelectTriggerIcon,
} from '@posthog/quill'

import { AggregationAxisFormat, INSIGHT_UNIT_OPTIONS } from 'scenes/insights/aggregationAxisFormat'

export interface QuillUnitPickerProps {
    displayValue: ReactNode
    format: AggregationAxisFormat | undefined
    prefix: string | undefined
    postfix: string | undefined
    onFormatChange: (format: AggregationAxisFormat) => void
    onCustomPrefix: () => void
    onCustomPostfix: () => void
}

export function QuillUnitPicker({
    displayValue,
    format,
    prefix,
    postfix,
    onFormatChange,
    onCustomPrefix,
    onCustomPostfix,
}: QuillUnitPickerProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" left className="w-full" data-attr="chart-aggregation-axis-format" />}
            >
                <span className="min-w-0 flex-1 truncate text-left">{displayValue}</span>
                <SelectTriggerIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup
                    value={format ?? ''}
                    onValueChange={(value: string) => onFormatChange(value as AggregationAxisFormat)}
                >
                    {INSIGHT_UNIT_OPTIONS.map(({ value, label }) => (
                        <DropdownMenuRadioItem key={value} value={value}>
                            {label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuCheckboxItem checked={!!prefix} onCheckedChange={onCustomPrefix}>
                    Custom prefix{prefix ? `: ${prefix}...` : '...'}
                </DropdownMenuCheckboxItem>
                <DropdownMenuCheckboxItem checked={!!postfix} onCheckedChange={onCustomPostfix}>
                    Custom postfix{postfix ? `: ${postfix}...` : '...'}
                </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
