import clsx from 'clsx'
import { useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { FunnelsQuery } from '~/queries/schema'

export function FunnnelInsightDataExploration(): JSX.Element {
    const { insightLoading, insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))

    // TODO: implement in funnelDataLogic
    const isValidFunnel = true

    const areFiltersValid = (querySource as FunnelsQuery).series.length > 0
    const nonEmptyState = (isValidFunnel && areFiltersValid) || insightLoading

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
    const { isValidFunnel, areFiltersValid } = useValues(funnelLogic(insightProps))
    const nonEmptyState = (isValidFunnel && areFiltersValid) || insightLoading

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
