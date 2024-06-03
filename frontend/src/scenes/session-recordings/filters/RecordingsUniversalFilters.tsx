import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { UniversalFilters } from 'lib/components/UniversalFilters/UniversalFilters'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'

import { sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'

export const RecordingsUniversalFilters = (): JSX.Element => {
    const { universalFilters } = useValues(sessionRecordingsPlaylistLogic)
    const { setUniversalFilters } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <div className="divide-y bg-bg-light rounded border">
            <div className="flex justify-between px-2 py-1.5">
                <div className="flex space-x-2">
                    <DateFilter
                        dateFrom={universalFilters.date_from ?? '-3d'}
                        dateTo={universalFilters.date_to}
                        disabled={universalFilters.live_mode}
                        onChange={(changedDateFrom, changedDateTo) => {
                            setUniversalFilters({
                                ...universalFilters,
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
                        filters={universalFilters}
                        onChange={(testFilters) =>
                            setUniversalFilters({
                                ...universalFilters,
                                filter_test_accounts: testFilters.filter_test_accounts,
                            })
                        }
                    />
                </div>
                <div>
                    <AndOrFilterSelect
                        value={universalFilters.filter_group.type}
                        onChange={(value) => {
                            setUniversalFilters({
                                ...universalFilters,
                                filter_group: {
                                    type: value,
                                    values: universalFilters.filter_group.values,
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
                    group={universalFilters.filter_group}
                    onChange={(filterGroup) => {
                        setUniversalFilters({
                            ...universalFilters,
                            filter_group: filterGroup,
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
