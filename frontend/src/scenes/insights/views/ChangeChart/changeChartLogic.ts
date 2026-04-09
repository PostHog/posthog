import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { teamLogic } from '~/scenes/teamLogic'
import { ChartParams, InsightLogicProps, TrendResult } from '~/types'

import {
    buildChangeChartRows,
    ChangeChartRow,
    formatChangeChartPercent,
    getChangeChartDisplayValue,
    getChangeChartDomain,
    getChangeChartVizOptions,
    sortChangeChartRows,
} from './changeChartData'

export interface ChangeChartLogicProps extends Pick<ChartParams, 'showPersonsModal' | 'inCardView'> {
    context?: QueryContext<InsightVizNode>
    insightProps: InsightLogicProps
}

export interface ChangeChartDisplayRow {
    key: string
    rawRow: ChangeChartRow
    label: string
    metricLabel: string
    currentValueLabel: string
    previousValueLabel: string
    changeLabel: string
}

export interface HoveredChangeChartTooltip {
    row: ChangeChartDisplayRow
    x: number
    y: number
}

function formatChangeChartPeriodLabel(dateFrom: string, dateTo: string): string {
    const start = dayjs(dateFrom)
    const end = dayjs(dateTo)

    if (!start.isValid() || !end.isValid()) {
        return 'Current period'
    }

    if (start.isSame(end, 'day')) {
        return `${start.format('MMM D, h:mm A')} - ${end.format('h:mm A')}`
    }

    return `${start.format('MMM D, h:mm A')} - ${end.format('MMM D, h:mm A')}`
}

export const changeChartLogic = kea([
    props({} as ChangeChartLogicProps),
    key((props) => keyForInsightLogicProps('change_chart')(props.insightProps)),
    path((key) => ['scenes', 'insights', 'views', 'ChangeChart', 'changeChartLogic', key]),

    connect((props: ChangeChartLogicProps) => ({
        values: [
            trendsDataLogic(props.insightProps),
            [
                'indexedResults',
                'insightData',
                'trendsFilter',
                'breakdownFilter',
                'querySource',
                'hasDataWarehouseSeries',
                'vizSpecificOptions',
            ],
            cohortsModel,
            ['allCohorts'],
            propertyDefinitionsModel,
            ['formatPropertyValueForDisplay'],
            teamLogic,
            ['baseCurrency'],
        ],
    })),

    actions({
        setHoveredTooltip: (row: ChangeChartDisplayRow, x: number, y: number) => ({ row, x, y }),
        clearHoveredTooltip: (key?: string) => ({ key }),
        openRow: (row: ChangeChartDisplayRow) => ({ row }),
    }),

    reducers({
        hoveredTooltip: [
            null as HoveredChangeChartTooltip | null,
            {
                setHoveredTooltip: (_, { row, x, y }) => ({ row, x, y }),
                clearHoveredTooltip: (state, { key }) => {
                    if (!state || !key || state.row.key === key) {
                        return null
                    }
                    return state
                },
                openRow: () => null,
            },
        ],
    }),

    selectors({
        changeChartOptions: [
            (s) => [s.vizSpecificOptions],
            (vizSpecificOptions) => getChangeChartVizOptions(vizSpecificOptions),
        ],

        displayMode: [(s) => [s.changeChartOptions], (changeChartOptions) => changeChartOptions.displayMode],

        showCurrentValue: [(s) => [s.changeChartOptions], (changeChartOptions) => changeChartOptions.showCurrentValue],

        changeChartDisplayRows: [
            (s) => [
                s.indexedResults,
                s.changeChartOptions,
                s.breakdownFilter,
                s.allCohorts,
                s.formatPropertyValueForDisplay,
                s.trendsFilter,
                s.baseCurrency,
            ],
            (
                indexedResults,
                changeChartOptions,
                breakdownFilter,
                allCohorts,
                formatPropertyValueForDisplay,
                trendsFilter,
                baseCurrency
            ): ChangeChartDisplayRow[] => {
                const formatValue = (value: number): string =>
                    formatAggregationAxisValue(trendsFilter, value, baseCurrency)
                const getLabel = (row: ChangeChartRow): string =>
                    formatBreakdownLabel(
                        row.breakdownValue,
                        breakdownFilter,
                        allCohorts?.results,
                        formatPropertyValueForDisplay
                    )
                const rawRows = sortChangeChartRows(buildChangeChartRows(indexedResults), changeChartOptions, getLabel)

                return rawRows.map((rawRow) => {
                    const changeValue = getChangeChartDisplayValue(rawRow, changeChartOptions.displayMode)
                    const absoluteChangeLabel =
                        changeValue === null
                            ? 'No previous data'
                            : !Number.isFinite(changeValue)
                              ? changeValue > 0
                                  ? '+inf'
                                  : '-inf'
                              : `${changeValue > 0 ? '+' : changeValue < 0 ? '-' : ''}${formatValue(
                                    Math.abs(changeValue)
                                )}`

                    return {
                        key: JSON.stringify(rawRow.breakdownValue ?? getLabel(rawRow)),
                        rawRow,
                        label: getLabel(rawRow),
                        metricLabel: rawRow.current?.label ?? rawRow.previous?.label ?? '',
                        currentValueLabel: formatValue(rawRow.currentValue),
                        previousValueLabel:
                            rawRow.previousValue === null ? 'No data' : formatValue(rawRow.previousValue),
                        changeLabel:
                            changeChartOptions.displayMode === 'absolute'
                                ? absoluteChangeLabel
                                : formatChangeChartPercent(rawRow.percentChange),
                    }
                })
            },
        ],

        changeChartDomain: [
            (s) => [s.changeChartDisplayRows, s.displayMode],
            (changeChartDisplayRows, displayMode) =>
                getChangeChartDomain(
                    changeChartDisplayRows.map((row) => row.rawRow),
                    displayMode
                ),
        ],

        axisLabels: [
            (s) => [s.changeChartDomain, s.displayMode, s.trendsFilter, s.baseCurrency],
            (changeChartDomain, displayMode, trendsFilter, baseCurrency): string[] => {
                const formatAxisValue = (value: number): string =>
                    displayMode === 'absolute'
                        ? formatAggregationAxisValue(trendsFilter, value, baseCurrency)
                        : `${value}%`

                return [-changeChartDomain, -(changeChartDomain / 2), 0, changeChartDomain / 2, changeChartDomain].map(
                    formatAxisValue
                )
            },
        ],

        currentPeriodLabel: [
            (s) => [s.insightData],
            (insightData): string => {
                const resolvedDateRange = insightData?.resolved_date_range
                if (resolvedDateRange?.date_from && resolvedDateRange?.date_to) {
                    return formatChangeChartPeriodLabel(resolvedDateRange.date_from, resolvedDateRange.date_to)
                }
                return 'Current period'
            },
        ],

        previousPeriodLabel: [
            (s) => [s.insightData],
            (insightData): string => {
                const resolvedDateRange = insightData?.resolved_date_range
                if (resolvedDateRange?.date_from && resolvedDateRange?.date_to) {
                    const currentStart = dayjs(resolvedDateRange.date_from)
                    const currentEnd = dayjs(resolvedDateRange.date_to)
                    const durationMs = currentEnd.diff(currentStart)

                    return formatChangeChartPeriodLabel(
                        currentStart.subtract(durationMs, 'millisecond').toISOString(),
                        currentEnd.subtract(durationMs, 'millisecond').toISOString()
                    )
                }
                return 'Previous period'
            },
        ],
    }),

    listeners(({ props, values }) => ({
        openRow: ({ row }) => {
            const referenceRow = (row.rawRow.current ?? row.rawRow.previous) as TrendResult | null
            if (!referenceRow) {
                return
            }

            if (props.context?.onDataPointClick) {
                props.context.onDataPointClick(
                    { breakdown: row.rawRow.breakdownValue, compare: 'current' },
                    referenceRow
                )
                return
            }

            if (!(props.showPersonsModal && values.querySource && !values.hasDataWarehouseSeries)) {
                return
            }

            openPersonsModal({
                title: row.label,
                query: {
                    kind: NodeKind.InsightActorsQuery,
                    source: values.querySource,
                    includeRecordings: true,
                    series: referenceRow.action?.order ?? 0,
                    breakdown: row.rawRow.breakdownValue,
                    compare: 'current',
                },
                additionalSelect: {
                    value_at_data_point: 'event_count',
                    matched_recordings: 'matched_recordings',
                },
                orderBy: ['event_count DESC, actor_id DESC'],
            })
        },
    })),
])
