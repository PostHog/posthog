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

import { WEB_ANALYTICS_PRE_AGGREGATED_PROPERTY_ALLOW_LIST } from './constants'
import { webAnalyticsLogic } from './webAnalyticsLogic'

/**
 * As of today, this file can be used in two modes:
 * 1. Web Analytics Dashboard mode: No props needed, uses webAnalyticsLogic
 * 2. Standalone mode: Pass webAnalyticsFilters and setWebAnalyticsFilters props
 *
 * This allows the component to be reused in Product Analytics insights.
 */

// Re-export for backward compatibility
export const WEB_ANALYTICS_PROPERTY_ALLOW_LIST = WEB_ANALYTICS_PRE_AGGREGATED_PROPERTY_ALLOW_LIST

export const getWebAnalyticsTaxonomicGroupTypes = (preAggregatedEnabled: boolean): TaxonomicFilterGroupType[] => [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.SessionProperties,
    ...(!preAggregatedEnabled ? [TaxonomicFilterGroupType.PersonProperties] : []),
]

export interface WebPropertyFiltersProps {
    webAnalyticsFilters?: AnyPropertyFilter[]
    setWebAnalyticsFilters?: (filters: AnyPropertyFilter[]) => void
}

export const WebPropertyFilters = ({
    webAnalyticsFilters: propsFilters,
    setWebAnalyticsFilters: propsSetFilters,
}: WebPropertyFiltersProps = {}): JSX.Element => {
    // Always call hooks unconditionally (React Rules of Hooks)
    const {
        rawWebAnalyticsFilters = [],
        preAggregatedEnabled = false,
        hasIncompatibleFilters = false,
    } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters: logicSetFilters } = useActions(webAnalyticsLogic)

    const webAnalyticsFilters = propsFilters ?? rawWebAnalyticsFilters
    const setWebAnalyticsFilters = propsSetFilters ?? logicSetFilters

    const [displayFilters, setDisplayFilters] = useState(false)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.SessionProperties,
        ...(!preAggregatedEnabled ? [TaxonomicFilterGroupType.PersonProperties] : []),
    ]

    const webAnalyticsPropertyAllowList = preAggregatedEnabled
        ? (WEB_ANALYTICS_PRE_AGGREGATED_PROPERTY_ALLOW_LIST as unknown as {
              [key: string]: string[]
          })
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
                        propertyFilters={webAnalyticsFilters}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                    />
                </div>
            }
        >
            <div className="relative">
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
                {hasIncompatibleFilters && (
                    <span className="absolute -top-1 -right-1 w-2 h-2 bg-warning rounded-full animate-pulse" />
                )}
            </div>
        </Popover>
    )
}
