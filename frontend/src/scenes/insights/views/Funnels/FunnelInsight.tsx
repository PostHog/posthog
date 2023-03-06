import clsx from 'clsx'
import { useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { FunnelsQuery } from '~/queries/schema'

export function FunnelInsightDataExploration(): JSX.Element {
    const { insightLoading, insightProps } = useValues(insightLogic)
    const { querySource, hasFunnelResults } = useValues(funnelDataLogic(insightProps))

    const areFiltersValid = (querySource as FunnelsQuery).series.length > 0
    const nonEmptyState = (hasFunnelResults && areFiltersValid) || insightLoading

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state': nonEmptyState,
            })}
        >
            <Funnel />
        </div>
    )
}

export function FunnelInsight(): JSX.Element {
    const { insightProps, insightLoading } = useValues(insightLogic)
    const { hasFunnelResults, areFiltersValid } = useValues(funnelLogic(insightProps))
    const nonEmptyState = (hasFunnelResults && areFiltersValid) || insightLoading

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state': nonEmptyState,
            })}
        >
            <Funnel />
        </div>
    )
}
