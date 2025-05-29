import { IconFilter } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
    const webAnalyticsPropertyAllowList = preAggregatedEnabled
        ? {
              [TaxonomicFilterGroupType.EventProperties]: [
                  '$host',
                  '$device_type',
                  '$browser',
                  '$browser_version',
                  '$os',
                  '$os_version',
                  '$referring_domain',
                  '$geoip_country_name',
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
                  '$entry_gclid',
                  '$entry_gad_source',
                  '$entry_gclsrc',
                  '$entry_dclid',
                  '$entry_gbraid',
                  '$entry_wbraid',
                  '$entry_fbclid',
                  '$entry_msclkid',
                  '$entry_twclid',
                  '$entry_li_fat_id',
                  '$entry_mc_cid',
                  '$entry_igshid',
                  '$entry_ttclid',
                  '$entry_epik',
                  '$entry_qclid',
                  '$entry_sccid',
                  '$entry__kx',
                  '$entry_irclid',
              ],
          }
        : undefined

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
