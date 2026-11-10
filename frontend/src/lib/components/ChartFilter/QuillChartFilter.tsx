import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    SelectTriggerIcon,
    Text,
} from '@posthog/quill'

import { ChartDisplayIcon } from 'lib/components/ChartFilter/ChartDisplayIcon'
import type { ChartDisplayOption, ChartDisplayOptionGroup } from 'lib/components/ChartFilter/chartDisplayOptions'

import { ChartDisplayType } from '~/types'

// Ordered by how often people pick them; the rest go under "More chart types".
const PRIMARY_DISPLAYS: ChartDisplayType[] = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.Metric,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.ActionsTable,
    ChartDisplayType.ActionsPie,
]

export interface QuillChartFilterProps {
    value: ChartDisplayType
    groups: ChartDisplayOptionGroup[]
    onChange: (value: ChartDisplayType) => void
    onOpen?: () => void
    fullWidth?: boolean
    disabledReason?: string | null
}

function splitGroups(groups: ChartDisplayOptionGroup[]): {
    primary: ChartDisplayOptionGroup[]
    more: ChartDisplayOptionGroup[]
} {
    const isPrimary = (option: ChartDisplayOption): boolean => PRIMARY_DISPLAYS.includes(option.display)
    const byUsage = (a: ChartDisplayOption, b: ChartDisplayOption): number =>
        PRIMARY_DISPLAYS.indexOf(a.display) - PRIMARY_DISPLAYS.indexOf(b.display)
    return {
        primary: groups
            .map((group) => ({ ...group, options: group.options.filter(isPrimary).sort(byUsage) }))
            .filter((group) => group.options.length > 0),
        more: groups
            .map((group) => ({ ...group, options: group.options.filter((option) => !isPrimary(option)) }))
            .filter((group) => group.options.length > 0),
    }
}

function ChartOptionGroups({
    groups,
    value,
    onChange,
}: {
    groups: ChartDisplayOptionGroup[]
    value: ChartDisplayType
    onChange: (value: ChartDisplayType) => void
}): JSX.Element {
    return (
        <DropdownMenuRadioGroup value={value} onValueChange={(next) => onChange(next as ChartDisplayType)}>
            {groups.map((group) => (
                <DropdownMenuGroup key={group.title}>
                    <DropdownMenuLabel inset>{group.title}</DropdownMenuLabel>
                    {group.options.map((option) => (
                        <DropdownMenuRadioItem
                            key={option.display}
                            value={option.display}
                            closeOnClick
                            tooltip={option.tooltip ?? option.description}
                            disabledReason={option.disabledReason}
                        >
                            <ChartDisplayIcon icon={option.icon} />
                            {option.label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuGroup>
            ))}
        </DropdownMenuRadioGroup>
    )
}

export function QuillChartFilter({
    value,
    groups,
    onChange,
    onOpen,
    fullWidth,
    disabledReason,
}: QuillChartFilterProps): JSX.Element {
    const { primary, more } = splitGroups(groups)
    const current = groups.flatMap((group) => group.options).find((option) => option.display === value)
    const currentInMore = more.some((group) => group.options.some((option) => option.display === value))

    return (
        <DropdownMenu onOpenChange={(open) => open && onOpen?.()}>
            <DropdownMenuTrigger
                disabled={!!disabledReason}
                render={
                    <Button
                        variant="outline"
                        left
                        disabledReason={disabledReason}
                        className={fullWidth ? 'w-full' : undefined}
                        data-attr="chart-filter"
                    />
                }
            >
                {current && <ChartDisplayIcon icon={current.icon} />}
                <span>{current?.label ?? value}</span>
                <SelectTriggerIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <ChartOptionGroups groups={primary} value={value} onChange={onChange} />
                {more.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger inset data-attr="chart-filter-more">
                                More chart types
                                {currentInMore && current && (
                                    <Text size="xs" variant="muted" render={<span className="ms-auto ps-4" />}>
                                        {current.label}
                                    </Text>
                                )}
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <ChartOptionGroups groups={more} value={value} onChange={onChange} />
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
