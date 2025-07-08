import { IconBolt, IconFilter } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useState } from 'react'

import { webAnalyticsLogic } from './webAnalyticsLogic'

export const WebPropertyFilters = (): JSX.Element => {
    const { rawWebAnalyticsFilters, preAggregatedEnabled } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters } = useActions(webAnalyticsLogic)

    const [displayFilters, setDisplayFilters] = useState(false)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.SessionProperties,
        ...(!preAggregatedEnabled ? [TaxonomicFilterGroupType.PersonProperties] : []),
    ]

    // Keep in sync with posthog/hogql_queries/web_analytics/stats_table_pre_aggregated.py

    // Create ordered property lists with optimized properties first
    const orderedEventProperties = [
        // Optimized properties first
        '$host',
        '$device_type',
        '$browser',
        '$os',
        '$referring_domain',
        '$geoip_country_code',
        '$geoip_city_name',
        '$geoip_subdivision_1_code',
        '$geoip_subdivision_1_name',
        '$geoip_time_zone',
        '$pathname',
        // Additional common properties that aren't optimized could go here
    ]

    const orderedSessionProperties = [
        // Optimized properties first
        '$entry_pathname',
        '$end_pathname',
        '$entry_utm_source',
        '$entry_utm_medium',
        '$entry_utm_campaign',
        '$entry_utm_term',
        '$entry_utm_content',
        // Additional common properties that aren't optimized could go here
    ]

    const webAnalyticsPropertyAllowList = preAggregatedEnabled
        ? {
              [TaxonomicFilterGroupType.EventProperties]: orderedEventProperties,
              [TaxonomicFilterGroupType.SessionProperties]: orderedSessionProperties,
          }
        : {
              [TaxonomicFilterGroupType.EventProperties]: orderedEventProperties,
              [TaxonomicFilterGroupType.SessionProperties]: orderedSessionProperties,
          }

    return (
        <Popover
            visible={displayFilters}
            onClickOutside={() => setDisplayFilters(false)}
            placement="bottom"
            className="max-w-200"
            overlay={
                <div className="p-2">
                    <PropertyFilters
                        disablePopover
                        propertyAllowList={webAnalyticsPropertyAllowList}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        onChange={(filters) =>
                            setWebAnalyticsFilters(filters.filter(isEventPersonOrSessionPropertyFilter))
                        }
                        propertyFilters={rawWebAnalyticsFilters}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                    />
                </div>
            }
        >
            <LemonButton
                icon={
                    <IconWithCount count={rawWebAnalyticsFilters.length} showZero={false}>
                        <div className="relative inline-flex">
                            <IconFilter />
                            {preAggregatedEnabled && (
                                <div className="absolute -top-1 -right-1 flex items-center justify-center">
                                    <Tooltip title="Using optimized query engine">
                                        <IconBolt className="text-orange-500 text-xs" />
                                    </Tooltip>
                                </div>
                            )}
                        </div>
                    </IconWithCount>
                }
                type="secondary"
                data-attr="show-web-analytics-filters"
                onClick={() => setDisplayFilters((displayFilters) => !displayFilters)}
            >
                Filters
            </LemonButton>
        </Popover>
    )
}
