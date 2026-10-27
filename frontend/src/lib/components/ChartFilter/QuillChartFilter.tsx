import {
    Button,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { ChartDisplayType } from '~/types'

import { ChartDisplayIcon } from 'products/product_analytics/frontend/insights/chartAlternatives/ChartDisplayIcon'
import type { ChartDisplayOptionGroup } from 'products/product_analytics/frontend/insights/chartAlternatives/chartDisplayOptions'

export interface QuillChartFilterProps {
    value: ChartDisplayType
    groups: ChartDisplayOptionGroup[]
    onChange: (value: ChartDisplayType) => void
    onOpen?: () => void
    fullWidth?: boolean
    disabledReason?: string | null
}

export function QuillChartFilter({
    value,
    groups,
    onChange,
    onOpen,
    fullWidth,
    disabledReason,
}: QuillChartFilterProps): JSX.Element {
    const options = groups.flatMap((group) => group.options)

    return (
        <Select<ChartDisplayType>
            value={value}
            onValueChange={(next) => next && onChange(next)}
            onOpenChange={(open) => open && onOpen?.()}
            disabled={!!disabledReason}
        >
            <SelectTrigger
                render={
                    <Button
                        variant="outline"
                        left
                        disabledReason={disabledReason}
                        className={fullWidth ? 'w-full' : undefined}
                    />
                }
                data-attr="chart-filter"
            >
                <SelectValue>
                    {(selected: ChartDisplayType) => {
                        const option = options.find((candidate) => candidate.display === selected)
                        return option ? (
                            <span className="flex items-center gap-2">
                                <ChartDisplayIcon icon={option.icon} />
                                {option.label}
                            </span>
                        ) : (
                            selected
                        )
                    }}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                {groups.map((group) => (
                    <SelectGroup key={group.title}>
                        <SelectGroupLabel>{group.title}</SelectGroupLabel>
                        {group.options.map((option) => (
                            <SelectItem key={option.display} value={option.display} disabled={!!option.disabledReason}>
                                <ChartDisplayIcon icon={option.icon} />
                                <span className="flex flex-col items-start gap-0.5">
                                    {option.label}
                                    <Text size="xs" variant="muted" render={<span />}>
                                        {option.disabledReason ?? option.description}
                                    </Text>
                                </span>
                            </SelectItem>
                        ))}
                    </SelectGroup>
                ))}
            </SelectContent>
        </Select>
    )
}
