import { useValues } from 'kea'
import { useMemo } from 'react'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'
import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { GoalLine as SchemaGoalLine, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { trendsDataLogic } from '../trendsDataLogic'
import type { IndexedTrendResult } from '../types'

interface TrendsLineChartD3Props {
    context?: QueryContext<InsightVizNode>
}

export function TrendsLineChartD3({ context }: TrendsLineChartD3Props): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const { insightProps } = useValues(insightLogic)

    const {
        indexedResults,
        display,
        interval,
        showPercentStackView,
        supportsPercentStackView,
        yAxisScaleType,
        goalLines,
        getTrendsColor,
        currentPeriodResult,
    } = useValues(trendsDataLogic(insightProps))
    const { timezone } = useValues(teamLogic)

    const labels = currentPeriodResult?.labels ?? []

    if (
        !(
            indexedResults &&
            indexedResults[0]?.data &&
            indexedResults.filter((result: IndexedTrendResult) => result.count !== 0).length > 0
        )
    ) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    const hogSeries: Series[] = indexedResults
        .filter((r: IndexedTrendResult) => r.count !== 0)
        .map((r: IndexedTrendResult) => ({
            key: `${r.id}`,
            label: r.label ?? '',
            data: r.data,
            color: getTrendsColor(r),
            fillArea: display === ChartDisplayType.ActionsAreaGraph,
        }))

    const xTickFormatter = createXAxisTickCallback({
        interval: interval ?? 'day',
        allDays: currentPeriodResult?.days ?? [],
        timezone,
    })

    const chartConfig: LineChartConfig = {
        showGrid: true,
        showCrosshair: true,
        yScaleType: yAxisScaleType === 'log10' ? 'log' : 'linear',
        percentStackView: !!showPercentStackView && !!supportsPercentStackView,
        xTickFormatter: xTickFormatter,
        goalLines: goalLines?.map((g: SchemaGoalLine) => ({
            value: g.value,
            label: g.label ?? undefined,
            borderColor: g.borderColor ?? undefined,
        })),
    }

    return <LineChart series={hogSeries} labels={labels} config={chartConfig} theme={theme} />
}
