import { CommonFilters } from 'lib/components/heatmaps/types'

import { buildElementStatsProperties } from '~/toolbar/elements/heatmapToolbarMenuLogic'
import { EntityTypes, FilterLogicalOperator, RecordingUniversalFilters } from '~/types'

// Reuses the clickmap's own stats filters, so the recordings link matches the same autocapture
// clicks the counts in the popup came from.
export function buildElementRecordingsFilters(
    selector: string,
    href: string,
    wildcardHref: string,
    commonFilters: CommonFilters
): Partial<RecordingUniversalFilters> {
    return {
        date_from: commonFilters.date_from,
        date_to: commonFilters.date_to,
        filter_test_accounts: commonFilters.filter_test_accounts,
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            id: '$autocapture',
                            name: '$autocapture',
                            type: EntityTypes.EVENTS,
                            order: 0,
                            properties: buildElementStatsProperties(href, wildcardHref, selector),
                        },
                    ],
                },
            ],
        },
    }
}
