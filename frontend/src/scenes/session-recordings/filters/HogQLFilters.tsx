import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { UniversalFilters, UniversalGroupFilterGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'

interface HogQLRecordingFilters {
    /**
     * live mode is front end only, sets date_from and date_to to the last hour
     */
    live_mode?: boolean
    date_from?: string | null
    date_to?: string | null
    filter_test_accounts?: boolean
    filterGroups: UniversalGroupFilterGroup
}

export const HogQLFilters = (): JSX.Element => {
    const [filters, setFilters] = useState<HogQLRecordingFilters>({
        live_mode: false,
        filter_test_accounts: false,
        date_from: '-3d',
        filterGroups: DEFAULT_UNIVERSAL_GROUP_FILTER,
    })

    return (
        <div className="divide-y bg-bg-light rounded border">
            <div className="flex justify-between px-2 py-1.5">
                <div className="flex space-x-2">
                    <DateFilter
                        dateFrom={filters.date_from ?? '-3d'}
                        dateTo={filters.date_to}
                        disabled={filters.live_mode}
                        onChange={(changedDateFrom, changedDateTo) => {
                            setFilters({
                                ...filters,
                                date_from: changedDateFrom,
                                date_to: changedDateTo,
                            })
                        }}
                        dateOptions={[
                            { key: 'Custom', values: [] },
                            { key: 'Last 24 hours', values: ['-24h'] },
                            { key: 'Last 3 days', values: ['-3d'] },
                            { key: 'Last 7 days', values: ['-7d'] },
                            { key: 'Last 30 days', values: ['-30d'] },
                            { key: 'All time', values: ['-90d'] },
                        ]}
                        dropdownPlacement="bottom-start"
                        size="small"
                    />
                    <TestAccountFilter
                        filters={filters}
                        onChange={(testFilters) =>
                            setFilters({ ...filters, filter_test_accounts: testFilters.filter_test_accounts })
                        }
                    />
                </div>
                <div>
                    <AndOrFilterSelect
                        value={filters.filterGroups.type}
                        onChange={(value) => {
                            setFilters({
                                ...filters,
                                filterGroups: {
                                    type: value,
                                    values: filters.filterGroups.values,
                                },
                            })
                        }}
                        topLevelFilter={true}
                        suffix={['filter', 'filters']}
                    />
                </div>
            </div>
            <div className="p-2">
                <UniversalFilters
                    group={filters.filterGroups}
                    onChange={(filterGroup) => {
                        setFilters({
                            ...filters,
                            filterGroups: filterGroup,
                        })
                    }}
                    pageKey="session-recordings"
                    taxonomicEntityFilterGroupTypes={[
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                    ]}
                    taxonomicPropertyFilterGroupTypes={[
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.SessionProperties,
                    ]}
                />
            </div>
        </div>
    )
}
