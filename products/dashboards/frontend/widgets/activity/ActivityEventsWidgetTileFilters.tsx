import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { NodeKind, type EventsQuery } from '~/queries/schema/schema-general'
import type { AnyPropertyFilter } from '~/types'

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
    const properties = (parsed.properties ?? []) as AnyPropertyFilter[]

    const { getLatestConfig, persistConfigDebounced, persistConfigNow } = useWidgetTileConfigPersist(
        onUpdateConfig,
        config
    )

    const controlDisabledReason = disabledReason
    const canUpdate = !!onUpdateConfig && !controlDisabledReason

    const applyDateFrom = async (value: WidgetDateFromValue): Promise<void> => {
        const nextConfig = patchActivityEventsWidgetFilterFields(getLatestConfig(), { dateFrom: value })
        await persistConfigNow(nextConfig)
    }

    const applyEventName = async (value: string | null): Promise<void> => {
        const nextConfig = patchActivityEventsWidgetFilterFields(getLatestConfig(), { eventName: value })
        await persistConfigNow(nextConfig)
    }

    const applyProperties = (value: AnyPropertyFilter[]): void => {
        const nextConfig = patchActivityEventsWidgetFilterFields(getLatestConfig(), { properties: value })
        persistConfigDebounced(nextConfig)
    }

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="activity-events-widget-tile-filters-readonly">
                <WidgetDateRangeReadOnlyValue dateFrom={dateFrom} />
                {eventName ? <WidgetTileFilterReadOnlyLabel name="Event" value={eventName} /> : null}
                {properties.length > 0 ? (
                    <WidgetTileFilterReadOnlyLabel
                        name="Properties"
                        value={`${properties.length} ${properties.length === 1 ? 'filter' : 'filters'}`}
                    />
                ) : null}
            </WidgetTileFiltersBar>
        )
    }

    const propertyFilterQuery: EventsQuery = {
        kind: NodeKind.EventsQuery,
        select: [],
        event: eventName ?? undefined,
        properties,
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
            {canUpdate && (
                <EventPropertyFilters
                    query={propertyFilterQuery}
                    setQuery={(query) => applyProperties(query.properties ?? [])}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                    ]}
                />
            )}
            {!canUpdate && properties.length > 0 && (
                <WidgetTileFilterReadOnlyLabel
                    name="Properties"
                    value={`${properties.length} ${properties.length === 1 ? 'filter' : 'filters'}`}
                />
            )}
        </WidgetTileFiltersBar>
    )
}
