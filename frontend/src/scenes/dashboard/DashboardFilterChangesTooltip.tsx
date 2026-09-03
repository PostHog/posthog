import type { ReactNode } from 'react'

import { IconCalendar, IconClock, IconFilter, IconPeople, IconSort } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { InsightDetailSectionDisplay } from 'lib/components/Cards/InsightCard/InsightDetails'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { DashboardFilterChange } from './dashboardFilterChanges'

interface DashboardFilterChangesTooltipProps {
    changes: DashboardFilterChange[]
    children: ReactNode
}

function getChangeIcon(label: DashboardFilterChange['label']): JSX.Element {
    if (label === 'Date range') {
        return <IconCalendar />
    }
    if (label === 'Grouped by') {
        return <IconClock />
    }
    if (label === 'Breakdown by') {
        return <IconSort />
    }
    if (label === 'Test accounts') {
        return <IconPeople />
    }
    return <IconFilter />
}

function ChangeValue({ value }: { value: string | string[] | undefined }): JSX.Element | null {
    if (!value) {
        return null
    }

    if (!Array.isArray(value)) {
        return <span className="break-all">{value}</span>
    }

    return (
        <span className="flex flex-wrap gap-1">
            {value.map((item) => (
                <LemonTag key={item} type="muted" size="small">
                    {item}
                </LemonTag>
            ))}
        </span>
    )
}

function renderChangeValue(change: DashboardFilterChange): JSX.Element {
    if (change.status === 'new') {
        return (
            <div className="flex flex-wrap items-center gap-1 font-medium">
                <strong>New:</strong> <ChangeValue value={change.value} />
            </div>
        )
    }
    if (change.status === 'removed') {
        return (
            <div className="flex flex-wrap items-center gap-1">
                <span className="font-medium">Removed</span>
                <span className="min-w-0 text-muted-alt">
                    was <ChangeValue value={change.previousValue} />
                </span>
            </div>
        )
    }
    return (
        <div className="flex flex-wrap items-center gap-1 break-words">
            <span className="font-medium">
                <ChangeValue value={change.value} />
            </span>
            <span className="min-w-0 text-muted-alt">
                was <ChangeValue value={change.previousValue} />
            </span>
        </div>
    )
}

export function DashboardFilterChangesTooltip({ changes, children }: DashboardFilterChangesTooltipProps): JSX.Element {
    if (!changes.length) {
        return <>{children}</>
    }

    return (
        <Tooltip
            placement="bottom-start"
            className="border border-primary bg-surface-primary p-4 text-primary"
            containerClassName="[--color-bg-surface-tooltip:var(--color-bg-surface-primary)]"
            interactive
            openOnClick
            title={
                <div className="max-w-sm">
                    <div className="mb-2 font-semibold">Filter changes</div>
                    <div className="InsightDetails space-y-2">
                        {changes.map((change, index) => (
                            <InsightDetailSectionDisplay
                                key={`${change.label}-${index}`}
                                icon={getChangeIcon(change.label)}
                                label={change.label}
                            >
                                {renderChangeValue(change)}
                            </InsightDetailSectionDisplay>
                        ))}
                    </div>
                </div>
            }
        >
            {children}
        </Tooltip>
    )
}
