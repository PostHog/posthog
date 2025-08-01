import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { webAnalyticsLogic } from './webAnalyticsLogic'

export const PREAGGREGATED_TABLE_SUPPORTED_PROPERTIES_BY_GROUP = {
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

export const WebPropertyFilters = (): JSX.Element => {
    const { rawWebAnalyticsFilters, preAggregatedEnabled } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters } = useActions(webAnalyticsLogic)

    const [displayFilters, setDisplayFilters] = useState(false)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.SessionProperties,
        ...(!preAggregatedEnabled ? [TaxonomicFilterGroupType.PersonProperties] : []),
    ]

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
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        onChange={(filters) =>
                            setWebAnalyticsFilters(filters.filter(isEventPersonOrSessionPropertyFilter))
                        }
                        propertyFilters={rawWebAnalyticsFilters}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                        enablePreaggregatedTableHints={preAggregatedEnabled}
                    />
                </div>
            }
        >
            <LemonButton
                icon={
                    <IconWithCount count={rawWebAnalyticsFilters.length} showZero={false}>
                        <IconFilter />
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
