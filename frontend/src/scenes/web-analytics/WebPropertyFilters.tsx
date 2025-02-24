import { IconFilter } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPersonOrSessionPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useState } from 'react'

import { WebAnalyticsPropertyFilters } from '~/queries/schema/schema-general'

export const WebPropertyFilters = ({
    webAnalyticsFilters,
    setWebAnalyticsFilters,
}: {
    webAnalyticsFilters: WebAnalyticsPropertyFilters
    setWebAnalyticsFilters: (filters: WebAnalyticsPropertyFilters) => void
}): JSX.Element => {
    const [displayFilters, setDisplayFilters] = useState(false)

    // Removing host because it's controlled by the domain filter and we don't want to display it here
    const propertyFilters = webAnalyticsFilters.filter((filter) => filter.key !== '$host')

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
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.SessionProperties,
                        ]}
                        excludedProperties={{
                            [TaxonomicFilterGroupType.EventProperties]: ['$host'],
                        }}
                        onChange={(filters) =>
                            // We want to ignore `$host` filters, they're controlled by the domain filter
                            // If this gets confusing, we'll need to find a way to block these filters from being added
                            setWebAnalyticsFilters(
                                filters
                                    .filter(isEventPersonOrSessionPropertyFilter)
                                    .filter((event) => event.key !== '$host')
                            )
                        }
                        propertyFilters={propertyFilters}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                    />
                </div>
            }
        >
            <LemonButton
                icon={
                    <IconWithCount count={propertyFilters.length} showZero={false}>
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
