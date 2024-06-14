import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { SceneExport } from 'scenes/sceneTypes'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { Query } from '~/queries/Query/Query'
import { AnyPropertyFilter } from '~/types'

import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { query } = useValues(errorTrackingSceneLogic)

    return (
        <div className="space-y-4">
            <Filters />
            <Query query={query} />
        </div>
    )
}

const Filters = (): JSX.Element => {
    const { dateRange, order, filterGroup, filterTestAccounts } = useValues(errorTrackingSceneLogic)
    const { setDateRange, setOrder, setFilterGroup, setFilterTestAccounts } = useActions(errorTrackingSceneLogic)

    return (
        <UniversalFilters
            rootKey="session-recordings"
            group={filterGroup}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]}
            onChange={(filterGroup) => {
                setFilterGroup(filterGroup)
            }}
        >
            <div className="divide-y bg-bg-light rounded border">
                <div className="flex justify-between px-2 py-1.5">
                    <div className="flex space-x-1">
                        <DateFilter
                            dateFrom={dateRange.date_from}
                            dateTo={dateRange.date_to}
                            onChange={(changedDateFrom, changedDateTo) => {
                                setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                            }}
                            size="small"
                        />
                        <LemonSelect
                            onSelect={setOrder}
                            onChange={setOrder}
                            value={order}
                            options={[
                                {
                                    value: 'last_seen',
                                    label: 'Last seen',
                                },
                                {
                                    value: 'first_seen',
                                    label: 'First seen',
                                },
                                {
                                    value: 'occurrences',
                                    label: 'Occurrences',
                                },
                                {
                                    value: 'users',
                                    label: 'Users',
                                },
                                {
                                    value: 'sessions',
                                    label: 'Sessions',
                                },
                            ]}
                            size="small"
                        />
                        <div>
                            <TestAccountFilter
                                filters={{ filter_test_accounts: filterTestAccounts }}
                                onChange={({ filter_test_accounts }) => {
                                    setFilterTestAccounts(filter_test_accounts || false)
                                }}
                                size="small"
                            />
                        </div>
                    </div>
                    <AndOrFilterSelect
                        onChange={(type) => setFilterGroup({ ...filterGroup, type: type })}
                        value={filterGroup.type}
                        topLevelFilter={true}
                        suffix={['filter', 'filters']}
                    />
                </div>
                <div className="flex flex-1 items-center space-x-2 px-2 py-1.5">
                    <RecordingsUniversalFilterGroup />
                    <UniversalFilters.AddFilterButton type="secondary" size="small" />
                </div>
            </div>
        </UniversalFilters>
    )
}

const RecordingsUniversalFilterGroup = (): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    const values = filterGroup.values as AnyPropertyFilter[]

    return (
        <>
            {values.map((filter, index) => (
                <UniversalFilters.Value
                    key={index}
                    index={index}
                    filter={filter}
                    onRemove={() => removeGroupValue(index)}
                    onChange={(value) => replaceGroupValue(index, value)}
                />
            ))}
        </>
    )
}
