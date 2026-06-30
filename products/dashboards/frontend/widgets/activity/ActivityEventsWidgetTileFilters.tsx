import { useRef } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { EventName } from 'products/actions/frontend/components/EventName'

import { WIDGET_DATE_RANGE_SELECT_OPTIONS, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import {
    WidgetDateRangeReadOnlyValue,
    WidgetTileFilterReadOnlyLabel,
    WidgetTileFiltersBar,
} from '../widgetTileFiltersReadOnly'
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
    const eventName = parsed.eventName ?? null

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

    const applyEventName = async (value: string | null): Promise<void> => {
        const nextConfig = patchActivityEventsWidgetFilterFields(configRef.current, { eventName: value })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="activity-events-widget-tile-filters-readonly">
                <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
                {eventName ? <WidgetTileFilterReadOnlyLabel name="Event" value={eventName} /> : null}
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
            <EventName
                value={eventName}
                allEventsOption="clear"
                disabled={!canUpdate}
                placeholder="All events"
                onChange={(value) => {
                    void applyEventName(value)
                }}
            />
        </WidgetTileFiltersBar>
    )
}
