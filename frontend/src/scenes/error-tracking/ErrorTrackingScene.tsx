import { LemonSelect, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
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
            <div className="divide-y bg-bg-light rounded border">
                <div className="flex justify-between px-2 py-1.5">
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
                            size="small"
                        />
                        <LemonSelect
                            onSelect={(newValue) => {
                                setFilters({ ...filters, order: newValue })
                            }}
                            onChange={(value) => {
                                setFilters({ ...filters, order: value })
                            }}
                            value={filters.order}
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
                                filters={filters}
                                onChange={(testFilters) => {
                                    setFilters({
                                        ...filters,
                                        filter_test_accounts: testFilters.filter_test_accounts || false,
                                    })
                                }}
                                size="small"
                            />
                        </div>
                    </div>
                    <AndOrFilterSelect
                        onChange={(type) => {
                            setFilters({
                                ...filters,
                                filter_group: { type: type, values: filters.filter_group.values },
                            })
                        }}
                        value={filters.filter_group.type}
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
