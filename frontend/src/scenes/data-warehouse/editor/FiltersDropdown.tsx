import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonDropdown } from '@posthog/lemon-ui'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { DateRange } from '~/queries/nodes/DataNode/DateRange'

import { sqlEditorLogic } from './sqlEditorLogic'

export function FiltersDropdown({ disabledReason }: { disabledReason?: string }): JSX.Element {
    const { sourceQuery, hasTestAccountFilters } = useValues(sqlEditorLogic)
    const { setSourceQuery, runQuery, setLocalDefault } = useActions(sqlEditorLogic)

    const hasDateRange = !!(
        sourceQuery.source.filters?.dateRange?.date_from || sourceQuery.source.filters?.dateRange?.date_to
    )
    const hasTestFilter = hasTestAccountFilters && !!sourceQuery.source.filters?.filterTestAccounts
    const activeFilterCount = (hasDateRange ? 1 : 0) + (hasTestFilter ? 1 : 0)

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="flex flex-col gap-2 p-2 min-w-64">
                    <DateRange
                        key="date-range"
                        query={sourceQuery.source}
                        setQuery={(query) => {
                            setSourceQuery({
                                ...sourceQuery,
                                source: query,
                            })
                            runQuery(query.query)
                        }}
                    />
                    <TestAccountFilterSwitch
                        checked={hasTestFilter}
                        onChange={(checked: boolean) => {
                            setSourceQuery({
                                ...sourceQuery,
                                source: {
                                    ...sourceQuery.source,
                                    filters: {
                                        ...sourceQuery.source.filters,
                                        filterTestAccounts: checked,
                                    },
                                },
                            })
                            setLocalDefault(checked)
                            runQuery()
                        }}
                        size="small"
                    />
                </div>
            }
        >
            <LemonButton
                icon={
                    <IconWithCount count={activeFilterCount} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
                disabledReason={disabledReason}
                tooltipDocLink={disabledReason ? 'https://posthog.com/docs/data-warehouse/sql/filters' : undefined}
                type="secondary"
                size="small"
                className="overflow-visible"
            >
                Filters
            </LemonButton>
        </LemonDropdown>
    )
}
