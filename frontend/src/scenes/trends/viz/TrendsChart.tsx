import { useValues } from 'kea'

import { getGraphColors } from 'lib/colors'
import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { Line } from 'lib/hog-charts'
import type { TooltipContext } from 'lib/hog-charts'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { ChartParams } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { trendsDataLogic } from '../trendsDataLogic'
import { buildGoalLines, buildYAxis } from './trendsChartUtils'
import { TrendsTooltip } from './TrendsTooltip'
import { useTrendsPersonsModal } from './useTrendsPersonsModal'

export function TrendsChart(props: ChartParams): JSX.Element | null {
    return (
        <ErrorBoundary exceptionProps={{ feature: 'TrendsChart' }}>
            <TrendsChartInner {...props} />
        </ErrorBoundary>
    )
}

function TrendsChartInner({ showPersonsModal = true, context }: ChartParams): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)

    const {
        indexedResults,
        interval,
        showValuesOnSeries,
        showMultipleYAxes,
        goalLines: schemaGoalLines,
        isArea,
        isStacked,
        isPercentStackView,
        isLog10,
        trendsSeries,
    } = useValues(trendsDataLogic(insightProps))

    const { alertThresholdLines } = useValues(
        insightAlertsLogic({ insightId: insight.id!, insightLogicProps: insightProps })
    )

    const handleClick = useTrendsPersonsModal({ showPersonsModal, context })

    if (!(indexedResults && indexedResults[0]?.data && indexedResults.filter((r) => r.count !== 0).length > 0)) {
        return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
    }

    const graphColors = getGraphColors()

    return (
        <Line
            theme={{
                axisColor: graphColors.axisLabel ?? '#94949480',
                gridColor: graphColors.axisLine ?? '#94949420',
            }}
            series={trendsSeries}
            yAxis={buildYAxis(isLog10, isPercentStackView, showMultipleYAxes ?? null, trendsSeries.length)}
            goalLines={buildGoalLines(alertThresholdLines, schemaGoalLines ?? undefined)}
            interval={interval ?? undefined}
            options={{
                stacked: isStacked,
                percentStacked: isPercentStackView,
                isArea,
                fillOpacity: isPercentStackView ? 1 : 0.5,
                showValues: !!showValuesOnSeries,
                maxSeries: 50,
            }}
            tooltip={{
                render: (ctx: TooltipContext) => (
                    <TrendsTooltip
                        context={ctx}
                        showPersonsModal={showPersonsModal}
                        groupTypeLabel={context?.groupTypeLabel}
                    />
                ),
            }}
            onClick={handleClick}
        />
    )
}
