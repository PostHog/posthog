import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, ItemMode } from '~/types'

import { billingUsageLogic } from './billingUsageLogic'

const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Feature Flags', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Persons', value: 'enhanced_persons_event_count_in_period' },
]

type BreakdownOption = { label: string; value: string | null }

const BREAKDOWN_OPTIONS: BreakdownOption[] = [
    { label: 'None', value: null },
    { label: 'By Type', value: 'type' },
    { label: 'By Team', value: 'team' },
    { label: 'By Type & Team', value: 'both' },
]

const INTERVAL_OPTIONS = [
    { label: 'Day', value: 'day' },
    { label: 'Week', value: 'week' },
    { label: 'Month', value: 'month' },
]

export function BillingUsage3(): JSX.Element {
    const logic = billingUsageLogic({ dashboardItemId: 'usage3' })
    const { series, dates, filters, dateFrom, dateTo } = useValues(logic)
    const { setFilters, setDateRange } = useActions(logic)

    const handleBreakdownChange = (value: string | null): void => {
        if (!value) {
            setFilters({ breakdowns: undefined })
        } else if (value === 'both') {
            setFilters({ breakdowns: ['type', 'team'] })
        } else {
            setFilters({ breakdowns: [value] })
        }
    }

    // Create data visualization query
    const dataVizQuery = {
        kind: NodeKind.DataVisualizationNode as const,
        source: {
            kind: NodeKind.HogQLQuery as const,
            query: '', // We don't need this since we're providing cached results
        },
        display: ChartDisplayType.ActionsLineGraph,
        chartSettings: {
            showLegend: true,
            yAxisAtZero: true,
            xAxis: {
                column: 'date',
            },
            yAxis: series.map((s, index) => ({
                column: s.label,
                settings: {
                    display: {
                        color: getSeriesColor(index),
                    },
                },
            })),
        },
    }

    // Transform our data into the format expected by DataVisualization
    const transformedData = {
        columns: ['date', ...series.map((s) => s.label)],
        types: [['date', 'DateTime'], ...series.map((s) => [s.label, 'Float'])],
        results: dates.map((date, i) => [date, ...series.map((s) => s.data[i])]),
    }

    const vizKey = 'billing-usage-3'
    const dataNodeCollectionId = 'billing-usage-3'

    const dataVisualizationLogicProps = {
        key: vizKey,
        query: dataVizQuery,
        dataNodeCollectionId,
        insightMode: ItemMode.View,
        cachedResults: transformedData,
    }

    const dataNodeLogicProps = {
        query: dataVizQuery.source,
        key: vizKey,
        cachedResults: transformedData,
        dataNodeCollectionId,
    }

    return (
        <div className="space-y-4">
            <h2>Usage Details (Direct LineGraph)</h2>

            <div className="flex gap-2 items-center flex-wrap">
                <LemonSelect
                    value={filters.usage_type}
                    options={USAGE_TYPES}
                    onChange={(value) => setFilters({ usage_type: value })}
                    placeholder="Select usage type"
                />
                <LemonSelect<string | null>
                    value={filters.breakdowns?.length === 2 ? 'both' : filters.breakdowns?.[0] || null}
                    options={BREAKDOWN_OPTIONS}
                    onChange={handleBreakdownChange}
                    placeholder="Select breakdown"
                />
                <LemonSelect
                    value={filters.interval || 'day'}
                    options={INTERVAL_OPTIONS}
                    onChange={(value) => setFilters({ interval: value as 'day' | 'week' | 'month' })}
                />
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(fromDate, toDate) => setDateRange(fromDate || null, toDate || null)}
                />
                <LemonButton
                    type="secondary"
                    onClick={() => setFilters({ compare: filters.compare ? undefined : 'previous_period' })}
                    active={!!filters.compare}
                >
                    Compare
                </LemonButton>
            </div>

            {!filters.usage_type && !filters.breakdowns?.includes('type') && (
                <LemonBanner type="info">
                    Please select a usage type or break down by type to see usage data
                </LemonBanner>
            )}

            {(filters.usage_type || filters.breakdowns?.includes('type')) && (
                <div className="border rounded p-4">
                    <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                        <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                            <BindLogic logic={displayLogic} props={{ key: vizKey }}>
                                <BindLogic
                                    logic={variablesLogic}
                                    props={{
                                        key: vizKey,
                                        readOnly: true,
                                        sourceQuery: dataVizQuery,
                                        setQuery: () => {},
                                    }}
                                >
                                    <BindLogic logic={variableModalLogic} props={{ key: vizKey }}>
                                        <LineGraph />
                                    </BindLogic>
                                </BindLogic>
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </div>
            )}
        </div>
    )
}
