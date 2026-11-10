import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import type { DashboardWidgetAppliedDateRangeApi } from '../generated/api.schemas'
import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../widget_types/widgetConfigShared'
import { WidgetDateRangeReadOnlyValue } from './widgetTileFiltersReadOnly'

export function WidgetDateRangeTileFilter({
    dateFrom,
    appliedDateRange,
    canUpdate,
    disabledReason,
    onChange,
}: {
    dateFrom: WidgetDateFromValue
    appliedDateRange?: DashboardWidgetAppliedDateRangeApi | null
    canUpdate: boolean
    disabledReason?: string | null
    onChange: (dateFrom: WidgetDateFromValue) => void
}): JSX.Element {
    // The widget's own range has no effect while a dashboard range applies, so it is not offered for editing.
    if (appliedDateRange) {
        return <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} appliedDateRange={appliedDateRange} />
    }
    return (
        <LemonSelect
            size="small"
            value={dateFrom}
            disabled={!canUpdate}
            disabledReason={disabledReason}
            options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
            onChange={(value) => {
                if (value) {
                    onChange(value)
                }
            }}
        />
    )
}
