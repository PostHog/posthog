import { useActions, useValues } from 'kea'

import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { WebConversionGoal } from 'scenes/web-analytics/WebConversionGoal'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'

import {
    InsightVizNode,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
} from '~/queries/schema/schema-general'
import { isWebStatsTableQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import { WebAnalyticsBreakdownSelector } from './WebAnalyticsBreakdownSelector'

export interface WebAnalyticsEditorFiltersProps {
    query: WebStatsTableQuery | WebOverviewQuery
    showing: boolean
    embedded: boolean
}

export function WebAnalyticsEditorFilters({ query, showing }: WebAnalyticsEditorFiltersProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { setQuery } = useActions(insightVizDataLogic(insightProps))
    const { query: insightVizNode } = useValues(insightVizDataLogic(insightProps as InsightLogicProps))

    const updateQuery = (updates: Partial<WebStatsTableQuery | WebOverviewQuery>): void => {
        if (insightVizNode && 'source' in insightVizNode) {
            setQuery({
                ...insightVizNode,
                source: {
                    ...insightVizNode.source,
                    ...updates,
                },
            } as InsightVizNode)
        }
    }

    const isStatsTable = isWebStatsTableQuery(query)
    const isPathBased =
        isStatsTable &&
        [WebStatsBreakdown.Page, WebStatsBreakdown.InitialPage, WebStatsBreakdown.ExitPage].includes(query.breakdownBy)

    if (!showing) {
        return null
    }

    return (
        <FilterBar
            left={
                <>
                    {isStatsTable && (
                        <WebAnalyticsBreakdownSelector
                            value={query.breakdownBy}
                            onChange={(breakdownBy) => updateQuery({ breakdownBy })}
                        />
                    )}
                </>
            }
            right={
                <>
                    <DateFilter
                        allowTimePrecision
                        dateFrom={query.dateRange?.date_from ?? '-7d'}
                        dateTo={query.dateRange?.date_to ?? null}
                        onChange={(date_from, date_to) =>
                            updateQuery({
                                dateRange: { date_from, date_to },
                            })
                        }
                    />
                    <CompareFilter
                        compare={query.compareFilter?.compare ?? false}
                        compareLabel={query.compareFilter?.compare_to}
                        onChange={(compare, compare_to) =>
                            updateQuery({
                                compareFilter: { compare, compare_to },
                            })
                        }
                    />
                    <WebConversionGoal
                        value={query.conversionGoal ?? null}
                        onChange={(conversionGoal) => updateQuery({ conversionGoal })}
                    />
                    {isPathBased && <PathCleaningToggle query={query} updateQuery={updateQuery} />}
                    <FilterTestAccountsToggle query={query} updateQuery={updateQuery} />
                    <WebPropertyFilters
                        webAnalyticsFilters={query.properties ?? []}
                        setWebAnalyticsFilters={(properties) => updateQuery({ properties })}
                    />
                </>
            }
        />
    )
}

function PathCleaningToggle({
    query,
    updateQuery,
}: {
    query: WebStatsTableQuery | WebOverviewQuery
    updateQuery: (updates: Partial<WebStatsTableQuery | WebOverviewQuery>) => void
}): JSX.Element {
    return (
        <Tooltip title="Clean paths by removing query parameters and standardizing URLs">
            <div className="flex items-center gap-2 px-2 py-1 border rounded">
                <span className="text-xs">Path cleaning</span>
                <LemonSwitch
                    checked={query.doPathCleaning ?? false}
                    onChange={(doPathCleaning) => updateQuery({ doPathCleaning })}
                />
            </div>
        </Tooltip>
    )
}

function FilterTestAccountsToggle({
    query,
    updateQuery,
}: {
    query: WebStatsTableQuery | WebOverviewQuery
    updateQuery: (updates: Partial<WebStatsTableQuery | WebOverviewQuery>) => void
}): JSX.Element {
    return (
        <Tooltip title="Filter out events from test accounts">
            <div className="flex items-center gap-2 px-2 py-1 border rounded">
                <span className="text-xs">Filter test accounts</span>
                <LemonSwitch
                    checked={query.filterTestAccounts ?? false}
                    onChange={(filterTestAccounts) => updateQuery({ filterTestAccounts })}
                />
            </div>
        </Tooltip>
    )
}
