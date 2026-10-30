import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import type { IntervalType } from '~/types'

import { addCrossProjectTileLogic } from './addCrossProjectTileLogic'
import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'
import { QuillCrossProjectDashboardLayoutActions } from './QuillCrossProjectDashboardLayoutActions'

const INTERVAL_OPTIONS: { value: IntervalType | null; label: string }[] = [
    { value: null, label: 'Default interval' },
    { value: 'hour', label: 'Hour' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
]

export function QuillCrossProjectDashboardActions(): JSX.Element | null {
    const { dashboard, dashboardFilters } = useValues(crossProjectDashboardLogic)
    const { setDates, setInterval, deleteDashboard } = useActions(crossProjectDashboardLogic)
    const { requestOpenModal } = useActions(addCrossProjectTileLogic({ dashboardId: dashboard?.id ?? '' }))

    if (!dashboard) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <DateFilter
                dateFrom={dashboardFilters.date_from ?? null}
                dateTo={dashboardFilters.date_to ?? null}
                onChange={setDates}
            />
            <Select<IntervalType | null>
                items={INTERVAL_OPTIONS}
                value={dashboardFilters.interval ?? null}
                onValueChange={(value) => setInterval(value)}
            >
                <SelectTrigger data-attr="cross-project-interval-filter">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {INTERVAL_OPTIONS.map((option) => (
                        <SelectItem key={option.value ?? 'default'} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <QuillCrossProjectDashboardLayoutActions />
            <Button variant="primary" onClick={requestOpenModal} data-attr="cross-project-add-tile">
                <IconPlus />
                Add insight
            </Button>
            <DropdownMenu>
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <DropdownMenuTrigger
                                render={
                                    <Button size="icon" aria-label="More" data-attr="cross-project-dashboard-more" />
                                }
                            />
                        }
                    >
                        <IconEllipsis />
                    </TooltipTrigger>
                    <TooltipContent>More</TooltipContent>
                </Tooltip>
                <DropdownMenuContent align="end" className="min-w-40">
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={deleteDashboard}
                        data-attr="cross-project-dashboard-delete"
                    >
                        Delete dashboard
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
