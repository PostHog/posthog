import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { AnyPropertyFilter } from '~/types'

import { webAnalyticsLogic } from './webAnalyticsLogic'

/**
 * As of today, this file can be used in two modes:
 * 1. Web Analytics Dashboard mode: No props needed, uses webAnalyticsLogic
 * 2. Standalone mode: Pass webAnalyticsFilters and setWebAnalyticsFilters props
 *
 * This allows the component to be reused in Product Analytics insights.
 */

export interface WebPropertyFiltersProps {
    webAnalyticsFilters?: AnyPropertyFilter[]
    setWebAnalyticsFilters?: (filters: AnyPropertyFilter[]) => void
}

export const WEB_ANALYTICS_PROPERTY_ALLOW_LIST = {
    [TaxonomicFilterGroupType.EventProperties]: [
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
        'metadata.loggedIn',
        'metadata.backend',
    ],
    [TaxonomicFilterGroupType.SessionProperties]: [
        '$entry_pathname',
        '$end_pathname',
        '$entry_utm_source',
        '$entry_utm_medium',
        '$entry_utm_campaign',
        '$entry_utm_term',
        '$entry_utm_content',
        '$channel_type',
    ],
}

export const getWebAnalyticsTaxonomicGroupTypes = (preAggregatedEnabled: boolean): TaxonomicFilterGroupType[] => [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.SessionProperties,
    ...(!preAggregatedEnabled ? [TaxonomicFilterGroupType.PersonProperties] : []),
]

export const WebPropertyFilters = ({
    webAnalyticsFilters: propsFilters,
    setWebAnalyticsFilters: propsSetFilters,
}: WebPropertyFiltersProps = {}): JSX.Element => {
    // Always call hooks unconditionally (React Rules of Hooks)
    const { rawWebAnalyticsFilters = [], preAggregatedEnabled = false } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters: logicSetFilters } = useActions(webAnalyticsLogic)

    const webAnalyticsFilters = propsFilters ?? rawWebAnalyticsFilters
    const setWebAnalyticsFilters = propsSetFilters ?? logicSetFilters

    const [displayFilters, setDisplayFilters] = useState(false)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.SessionProperties,
        ...(!preAggregatedEnabled ? [TaxonomicFilterGroupType.PersonProperties] : []),
    ]

    // Keep in sync with posthog/hogql_queries/web_analytics/stats_table_pre_aggregated.py
    const webAnalyticsPropertyAllowList = preAggregatedEnabled ? WEB_ANALYTICS_PROPERTY_ALLOW_LIST : undefined

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
                        propertyFilters={webAnalyticsFilters}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                    />
                </div>
            }
        >
            <LemonButton
                icon={
                    <IconWithCount count={webAnalyticsFilters.length} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
                type="secondary"
                data-attr="show-web-analytics-filters"
                onClick={() => setDisplayFilters((displayFilters) => !displayFilters)}
                size="small"
            >
                Filters
            </LemonButton>
        </Popover>
    )
}
