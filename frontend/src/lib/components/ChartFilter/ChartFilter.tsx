import React from 'react'
import { useValues, useActions } from 'kea'
import { Select, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_LINE_GRAPH_CUMULATIVE, STICKINESS, FUNNEL_STEPS } from '~/lib/constants'
import { IntervalFilter } from 'lib/components/IntervalFilter/IntervalFilter.tsx'
import { chartFilterLogic } from './chartFilterLogic'

interface Filters {
    display: string
    session: string
    shown_as: string
}

interface Props {
    onChange: (displayMode: string) => void
    filters: Filters
    displayMap: { [displayMode: string]: string }
    shouldShowIntervalFilter: (viewType: string, chartDisplay?: string) => boolean
    activeView: string
}

function shouldShowUserDatapointsTooltip(filters: Filters): boolean {
    return (
        !filters.display ||
        filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
        filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE
    )
}

export function ChartFilter({
    onChange,
    filters,
    displayMap,
    shouldShowIntervalFilter,
    activeView,
}: Props): JSX.Element {
    const { chartFilterTrends, chartFilterFunnels } = useValues(chartFilterLogic)
    const { setChartFilterTrends, setChartFilterFunnels } = useActions(chartFilterLogic)

    const isOnFunnelsView = activeView === 'FUNNELS'

    return (
        <>
            {shouldShowUserDatapointsTooltip(filters) && (
                <Tooltip
                    key="chart-users-tooltip"
                    getPopupContainer={(trigger) => trigger.parentElement!}
                    placement="right"
                    title="Click on a point to see users related to the datapoint"
                >
                    <InfoCircleOutlined className="info" style={{ color: '#007bff' }}></InfoCircleOutlined>
                </Tooltip>
            )}
            {shouldShowIntervalFilter(activeView, isOnFunnelsView ? chartFilterFunnels : chartFilterTrends) && (
                <IntervalFilter key="chart-interval-filter" view={activeView} />
            )}
            {isOnFunnelsView ? (
                <Select
                    key="chart-display-select-funnel"
                    defaultValue={displayMap[filters.display || FUNNEL_STEPS]}
                    value={displayMap[chartFilterFunnels || FUNNEL_STEPS]}
                    onChange={(value) => {
                        setChartFilterFunnels(value)
                        onChange(value)
                    }}
                    bordered={false}
                    dropdownMatchSelectWidth={false}
                    data-attr="chart-filter"
                >
                    <Select.Option value="FunnelViz" key="chart-type-steps">
                        Steps
                    </Select.Option>
                    <Select.Option value="FunnelTrends" key="chart-type-trends">
                        Trends
                    </Select.Option>
                </Select>
            ) : (
                <Select
                    key="chart-display-select-trend"
                    defaultValue={displayMap[filters.display || ACTIONS_LINE_GRAPH_LINEAR]}
                    value={displayMap[chartFilterTrends || ACTIONS_LINE_GRAPH_LINEAR]}
                    onChange={(value) => {
                        setChartFilterTrends(value)
                        onChange(value)
                    }}
                    bordered={false}
                    dropdownMatchSelectWidth={false}
                    data-attr="chart-filter"
                >
                    <Select.OptGroup label="Line Chart" key="chart-type-table">
                        <Select.Option
                            value={ACTIONS_LINE_GRAPH_LINEAR}
                            disabled={filters.session && filters.session === 'dist'}
                        >
                            Linear
                        </Select.Option>
                        <Select.Option
                            value={ACTIONS_LINE_GRAPH_CUMULATIVE}
                            disabled={filters.session || filters.shown_as === STICKINESS}
                        >
                            Cumulative
                        </Select.Option>
                    </Select.OptGroup>
                    <Select.Option value="ActionsTable" key="chart-type-table">
                        Table
                    </Select.Option>
                    <Select.Option value="ActionsPie" disabled={filters.session} key="chart-type-pie">
                        Pie
                    </Select.Option>
                </Select>
            )}
        </>
    )
}
