import { LemonLabel } from '@posthog/lemon-ui'
import { Label } from '@posthog/quill'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cdpFiltersToSeries, seriesToCdpFilters } from 'scenes/hog-functions/filters/cdpFilterSeries'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, ChartDisplayCategory } from '~/types'

import {
    UsageMetricFormData,
    UsageMetricSource,
    actionFilterValueToSavedFilters,
    savedFiltersToActionFilterValue,
} from './usageMetricsConfigLogic'

export function UsageMetricFiltersEditor({
    value,
    onChange,
    source,
    taxonomicGroupTypes,
}: {
    value: UsageMetricFormData['filters']
    onChange: (filters: UsageMetricFormData['filters']) => void
    source: UsageMetricSource
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const actionFilterValue = savedFiltersToActionFilterValue(value)

    return (
        <>
            <SeriesActionFilter
                bordered
                series={cdpFiltersToSeries(actionFilterValue)}
                onChange={(series) => {
                    onChange(actionFilterValueToSavedFilters(seriesToCdpFilters(series), source))
                }}
                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                typeKey="usage-metric-filters"
                mathAvailability={MathAvailability.None}
                hideRename
                hideDuplicate
                showNestedArrow={false}
                entitiesLimit={source === 'data_warehouse' ? 1 : undefined}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.DataWarehouse]}
                propertiesTaxonomicGroupTypes={taxonomicGroupTypes}
                propertyFiltersPopover
                dataWarehousePopoverFields={[
                    { key: 'timestamp_field', label: 'Timestamp column', allowHogQL: true },
                    { key: 'key_field', label: 'Group key column' },
                ]}
                newSeriesDefaults={{
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                }}
                buttonCopy={
                    (actionFilterValue?.events ?? []).length > 0 ? 'Add event' : 'Match event or data warehouse table'
                }
            />
            {source === 'events' && (
                <>
                    <div className="flex gap-2 justify-between w-full">
                        {todayRailNav ? <Label>Filters</Label> : <LemonLabel>Filters</LemonLabel>}
                    </div>
                    <PropertyFilters
                        propertyFilters={(actionFilterValue?.properties ?? []) as AnyPropertyFilter[]}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        onChange={(properties: AnyPropertyFilter[]) => {
                            onChange(actionFilterValueToSavedFilters({ ...actionFilterValue, properties }, source))
                        }}
                        pageKey="UsageMetricsConfig"
                    />
                    <TestAccountFilterSwitch
                        checked={actionFilterValue?.filter_test_accounts ?? false}
                        onChange={(filter_test_accounts) => {
                            onChange(
                                actionFilterValueToSavedFilters({ ...actionFilterValue, filter_test_accounts }, source)
                            )
                        }}
                        fullWidth
                    />
                </>
            )}
        </>
    )
}
