import type { ReactNode } from 'react'

import { IconCalendar, IconClock, IconFilter, IconPeople, IconSort } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { InsightDetailSectionDisplay } from 'lib/components/Cards/InsightCard/InsightDetails'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { DashboardFilterChange } from './dashboardChanges'

interface DashboardSettingsChangesTooltipProps {
    changes: DashboardFilterChange[]
    children: ReactNode
    title?: string
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

function ChangeValue({ value }: { value: string[] }): JSX.Element {
    if (value.length === 0) {
        return <span>Default</span>
    }

    if (value.length === 1) {
        return <span className="break-all">{value[0]}</span>
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
    return (
        <div className="flex flex-wrap items-center gap-1 break-words">
            <span className="min-w-0 text-muted-alt">
                <ChangeValue value={change.previousValue} />
            </span>
            <span aria-hidden="true">→</span>
            <span className="font-medium">
                <ChangeValue value={change.value} />
            </span>
        </div>
    )
}

export function DashboardSettingsChangesTooltip({
    changes,
    children,
    title = 'Filter changes',
}: DashboardSettingsChangesTooltipProps): JSX.Element {
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
                    <div className="mb-2 font-semibold">{title}</div>
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
