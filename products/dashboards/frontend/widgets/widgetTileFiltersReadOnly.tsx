import type { ReactNode } from 'react'
import { useMemo } from 'react'

import type { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import type { QuickFilter } from '~/types'

import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
} from 'products/error_tracking/frontend/components/Assignee/AssigneeDisplay'
import { LabelIndicator, StatusIndicator } from 'products/error_tracking/frontend/components/Indicators'
import type { ErrorTrackingStatusSelectValue } from 'products/error_tracking/frontend/components/IssueFilters/Status'

import {
    WIDGET_DATE_RANGE_SELECT_OPTIONS,
    type WidgetDateFromValue,
    type WidgetFilterConfigRecord,
} from '../widget_types/configSchemas'

export function isWidgetTileFiltersReadOnly(
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>
): boolean {
    return !onUpdateConfig
}

export function widgetDateRangeLabel(dateFrom: WidgetDateFromValue): string {
    return WIDGET_DATE_RANGE_SELECT_OPTIONS.find((option) => option.value === dateFrom)?.label ?? dateFrom
}

export function WidgetTileFiltersBar({ children, dataAttr }: { children: ReactNode; dataAttr: string }): JSX.Element {
    return (
        <div
            className="flex min-w-0 flex-wrap items-center gap-2 px-3 py-2 border-b border-primary"
            data-attr={dataAttr}
            onMouseDown={(event) => event.stopPropagation()}
        >
            {children}
        </div>
    )
}

export function WidgetTileFilterReadOnlyValue({
    children,
    className,
}: {
    children: ReactNode
    className?: string
}): JSX.Element {
    return <span className={className ?? 'inline-flex items-center gap-1.5 text-xs text-primary'}>{children}</span>
}

export function WidgetDateRangeReadOnlyValue({ dateFrom }: { dateFrom: WidgetDateFromValue }): JSX.Element {
    return <WidgetTileFilterReadOnlyValue>{widgetDateRangeLabel(dateFrom)}</WidgetTileFilterReadOnlyValue>
}

export function ErrorTrackingStatusReadOnlyValue({ status }: { status: ErrorTrackingStatusSelectValue }): JSX.Element {
    if (status === 'all') {
        return (
            <WidgetTileFilterReadOnlyValue>
                <LabelIndicator intent="muted" label="All" size="small" />
            </WidgetTileFilterReadOnlyValue>
        )
    }
    return (
        <WidgetTileFilterReadOnlyValue>
            <StatusIndicator status={status} size="small" />
        </WidgetTileFilterReadOnlyValue>
    )
}

export function ErrorTrackingAssigneeReadOnlyValue({
    assignee,
}: {
    assignee: ErrorTrackingIssue['assignee']
}): JSX.Element {
    return (
        <WidgetTileFilterReadOnlyValue>
            <AssigneeIconDisplay assignee={assignee} size="small" />
            <AssigneeLabelDisplay
                assignee={assignee}
                placeholder="Any assignee"
                size="small"
                className="text-primary"
            />
        </WidgetTileFilterReadOnlyValue>
    )
}

function widgetFilterReadOnlyLabel(
    filter: QuickFilter,
    entry: { optionId: string; value?: string | string[] | null }
): string {
    const option = filter.options.find((opt) => opt.id === entry.optionId)
    return option?.label ?? String(entry.value ?? '')
}

export function WidgetPropertyFiltersReadOnlyValues({
    filterDefinitions,
    widgetFilters,
}: {
    filterDefinitions: QuickFilter[]
    widgetFilters: WidgetFilterConfigRecord | undefined
}): JSX.Element | null {
    const stored = widgetFilters ?? {}

    const labels = useMemo(() => {
        return filterDefinitions
            .map((filter) => {
                const entry = stored[filter.id]
                if (!entry) {
                    return null
                }
                return { id: filter.id, name: filter.name, value: widgetFilterReadOnlyLabel(filter, entry) }
            })
            .filter((item): item is { id: string; name: string; value: string } => item != null)
    }, [filterDefinitions, stored])

    if (labels.length === 0) {
        return null
    }

    return (
        <>
            {labels.map((item) => (
                <WidgetTileFilterReadOnlyValue key={item.id}>
                    <span className="text-secondary">{item.name}:</span> {item.value}
                </WidgetTileFilterReadOnlyValue>
            ))}
        </>
    )
}
