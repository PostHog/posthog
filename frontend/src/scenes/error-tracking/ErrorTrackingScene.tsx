import { LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter } from '~/types'

import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { errorGroups, errorGroupsLoading } = useValues(errorTrackingSceneLogic)

    return (
        <div className="space-y-4">
            <Filters />
            <LemonTable
                columns={[
                    {
                        dataIndex: 'title',
                        width: '50%',
                        render: (_, group) => (
                            <LemonTableLink
                                title={group.title}
                                description={<div className="line-clamp-1">{group.description}</div>}
                                to={urls.errorTrackingGroup(group.id)}
                            />
                        ),
                    },
                    {
                        title: 'Occurrences',
                        dataIndex: 'occurrences',
                        sorter: (a, b) => a.occurrences - b.occurrences,
                    },
                    {
                        title: 'Sessions',
                        dataIndex: 'uniqueSessions',
                        sorter: (a, b) => a.uniqueSessions - b.uniqueSessions,
                    },
                    {
                        title: 'Users',
                        dataIndex: 'uniqueUsers',
                        sorter: (a, b) => a.uniqueUsers - b.uniqueUsers,
                    },
                ]}
                loading={errorGroupsLoading}
                dataSource={errorGroups}
            />
        </div>
    )
}

const Filters = (): JSX.Element => {
    const { filters } = useValues(errorTrackingSceneLogic)
    const { setFilters } = useActions(errorTrackingSceneLogic)

    return (
        <div className="flex space-x-4">
            <div className="flex space-x-1">
                <DateFilter
                    dateFrom={filters.date_from}
                    dateTo={filters.date_to}
                    onChange={(changedDateFrom, changedDateTo) => {
                        setFilters({
                            ...filters,
                            date_from: changedDateFrom,
                            date_to: changedDateTo,
                        })
                    }}
                />
                <div>
                    <TestAccountFilter
                        filters={filters}
                        onChange={(testFilters) => {
                            setFilters({
                                ...filters,
                                filter_test_accounts: testFilters.filter_test_accounts || false,
                            })
                        }}
                    />
                </div>
            </div>
            <div className="flex flex-1 items-center space-x-2">
                <UniversalFilters
                    rootKey="session-recordings"
                    group={filters.filter_group}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]}
                    onChange={(filterGroup) => {
                        setFilters({
                            ...filters,
                            filter_group: filterGroup,
                        })
                    }}
                >
                    <RecordingsUniversalFilterGroup />
                    <UniversalFilters.AddFilterButton type="secondary" />
                </UniversalFilters>
            </div>
        </div>
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
