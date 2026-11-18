import { LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { IntervalType } from '~/types'

import type { CrossProjectDashboardFilters } from './crossProjectDashboardLogic'
import type { CrossProjectDashboardTileApi } from './generated/api.schemas'

interface DateRangeValue {
    date_from?: string | null
    date_to?: string | null
}

/** Single-project's "Set override" dialog, limited to dates and interval because other overrides resolve against one project. */
export function openCrossProjectTileOverrideDialog(
    tile: CrossProjectDashboardTileApi,
    onSave: (overrides: CrossProjectDashboardFilters) => void
): void {
    const current = (tile.filters_overrides ?? {}) as CrossProjectDashboardFilters

    LemonDialog.openForm({
        title: 'Override tile filters',
        maxWidth: '40rem',
        initialValues: {
            dateRange: { date_from: current.date_from ?? null, date_to: current.date_to ?? null },
            interval: current.interval ?? null,
        },
        content: (
            <div className="flex flex-col gap-4">
                <LemonField name="dateRange" label="Date range">
                    {({ value, onChange }: { value: DateRangeValue; onChange: (value: DateRangeValue) => void }) => (
                        <DateFilter
                            showCustom
                            dateFrom={value?.date_from ?? null}
                            dateTo={value?.date_to ?? null}
                            onChange={(dateFrom, dateTo) => onChange({ date_from: dateFrom, date_to: dateTo })}
                        />
                    )}
                </LemonField>
                <LemonField name="interval" label="Interval">
                    <LemonSelect<IntervalType | null>
                        options={[
                            { value: null, label: 'Follow the dashboard' },
                            { value: 'hour', label: 'Hour' },
                            { value: 'day', label: 'Day' },
                            { value: 'week', label: 'Week' },
                            { value: 'month', label: 'Month' },
                        ]}
                    />
                </LemonField>
            </div>
        ),
        tertiaryButton: {
            children: 'Clear all overrides',
            onClick: () => onSave({}),
        },
        onSubmit: (values) => {
            const dateRange = (values.dateRange ?? {}) as DateRangeValue
            const overrides: CrossProjectDashboardFilters = {}
            if (dateRange.date_from) {
                overrides.date_from = dateRange.date_from
            }
            if (dateRange.date_to) {
                overrides.date_to = dateRange.date_to
            }
            if (values.interval) {
                overrides.interval = values.interval as IntervalType
            }
            onSave(overrides)
        },
    })
}
