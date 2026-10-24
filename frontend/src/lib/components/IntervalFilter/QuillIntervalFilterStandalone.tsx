import type { LemonSelectOptionLeaf } from '@posthog/lemon-ui'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { IntervalType } from '~/types'

export interface QuillIntervalFilterStandaloneProps {
    disabled?: boolean
    disabledReason?: string | null
    interval: IntervalType
    onIntervalChange: (interval: IntervalType) => void
    options: LemonSelectOptionLeaf<IntervalType>[]
}

export function QuillIntervalFilterStandalone({
    disabled,
    disabledReason,
    interval,
    onIntervalChange,
    options,
}: QuillIntervalFilterStandaloneProps): JSX.Element {
    const visibleOptions = options.filter((option) => !option.hidden || option.value === interval)

    return (
        <Select<IntervalType>
            value={interval}
            onValueChange={(value) => value && onIntervalChange(value)}
            disabled={disabled || !!disabledReason}
        >
            <SelectTrigger
                render={<Button variant="outline" left disabledReason={disabledReason} />}
                data-attr="interval-filter"
            >
                <SelectValue>
                    {(value: IntervalType) => options.find((option) => option.value === value)?.label ?? value}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {visibleOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value} disabled={!!option.disabledReason}>
                        <span className="flex flex-col items-start gap-0.5">
                            {option.label}
                            {option.disabledReason && (
                                <Text
                                    size="xs"
                                    variant="muted"
                                    render={<span className="max-w-64 whitespace-normal" />}
                                >
                                    {option.disabledReason}
                                </Text>
                            )}
                        </span>
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
