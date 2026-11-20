import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { Text } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { IntervalType } from '~/types'

import { QuillToolbarSelect } from 'products/product_analytics/frontend/insights/shared/QuillToolbarSelect'

const INTERVAL_OPTIONS: { value: IntervalType | null; label: string }[] = [
    { value: null, label: "each insight's interval" },
    { value: 'hour', label: 'hour' },
    { value: 'day', label: 'day' },
    { value: 'week', label: 'week' },
    { value: 'month', label: 'month' },
]

export function DashboardIntervalFilter(): JSX.Element {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setInterval, setDashboardEditing } = useActions(dashboardLogic)
    const quillSurface = useQuillSurface()

    const onChange = (interval: IntervalType | null): void => {
        if (!dashboardEditing) {
            setDashboardEditing(true, DashboardEventSource.DashboardFilters)
        }
        setInterval(interval)
    }

    if (quillSurface) {
        return (
            <span className="flex items-center gap-2">
                <Text size="xs" render={<span className="hidden md:inline" />}>
                    grouped by
                </Text>
                <QuillToolbarSelect<IntervalType | null>
                    value={effectiveEditBarFilters.interval ?? null}
                    onChange={onChange}
                    options={INTERVAL_OPTIONS}
                    data-attr="dashboard-interval-filter"
                />
            </span>
        )
    }

    return (
        <span className="flex items-center gap-2">
            <span className="hidden md:inline">grouped by</span>
            <LemonSelect<IntervalType | null>
                size="small"
                value={effectiveEditBarFilters.interval ?? null}
                dropdownMatchSelectWidth={false}
                onChange={onChange}
                options={INTERVAL_OPTIONS}
            />
        </span>
    )
}
