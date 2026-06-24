import { useRef } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetDateRangeReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    parseActivityEventsWidgetConfig,
    patchActivityEventsWidgetFilterFields,
} from './activityEventsWidgetConfigValidation'

export type ActivityEventsWidgetTileFiltersProps = DashboardWidgetTileFiltersProps

export function ActivityEventsWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: ActivityEventsWidgetTileFiltersProps): JSX.Element {
    const parsed = parseActivityEventsWidgetConfig(config)
    const dateFrom = (parsed.dateRange?.date_from ?? '-24h') as WidgetDateFromValue

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig)

    const controlDisabledReason = disabledReason
    const canUpdate = !!onUpdateConfig && !controlDisabledReason

    const applyDateFrom = async (value: WidgetDateFromValue): Promise<void> => {
        const nextConfig = patchActivityEventsWidgetFilterFields(configRef.current, { dateFrom: value })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="activity-events-widget-tile-filters-readonly">
                <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="activity-events-widget-tile-filters">
            <LemonSelect
                size="small"
                value={dateFrom}
                disabled={!canUpdate}
                disabledReason={controlDisabledReason}
                options={WIDGET_DATE_RANGE_SELECT_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        void applyDateFrom(value)
                    }
                }}
            />
        </WidgetTileFiltersBar>
    )
}
