import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'
import { AnyPropertyFilter } from '~/types'

import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { dateRange, order, filterTestAccounts, filterGroup } = useValues(errorTrackingSceneLogic)

    const context: QueryContext = {
        columns: {
            'any(properties) -- Error': {
                width: '50%',
                render: CustomGroupTitleColumn,
            },
        },
        showOpenEditorButton: false,
    }

    return (
        <div className="space-y-4">
            <Filters />
            <Query
                query={{
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: [
                            'any(properties) -- Error',
                            'properties.$exception_type',
                            'count() as unique_occurrences -- Occurrences',
                            'count(distinct $session_id) as unique_sessions -- Sessions',
                            'count(distinct distinct_id) as unique_users -- Users',
                            'max(timestamp) as last_seen',
                            'min(timestamp) as first_seen',
                        ],
                        event: '$exception',
                        orderBy: [order],
                        after: dateRange.date_from,
                        before: dateRange.date_to,
                        filterTestAccounts,
                        properties: filterGroup.values,
                    },
                    hiddenColumns: [
                        'properties.$exception_type',
                        'first_value(properties)',
                        'max(timestamp) as last_seen',
                        'min(timestamp) as first_seen',
                    ],
                    showActions: false,
                    showTimings: false,
                }}
                context={context}
            />
        </div>
    )
}

const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const { value } = props
    const properties = JSON.parse(value as string)

    return (
        <LemonTableLink
            title={properties.$exception_type}
            description={<div className="line-clamp-1">{properties.$exception_message}</div>}
            to={urls.errorTrackingGroup(properties.$exception_type)}
        />
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
                <div className="flex space-x-1 justify-between px-2 py-1.5">
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
                                    value: 'unique_occurrences',
                                    label: 'Occurrences',
                                },
                                {
                                    value: 'unique_users',
                                    label: 'Users',
                                },
                                {
                                    value: 'unique_sessions',
                                    label: 'Sessions',
                                },
                            ]}
                            size="small"
                        />
                    </div>
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
