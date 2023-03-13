import clsx from 'clsx'
import { useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel, FunnelDataExploration } from 'scenes/funnels/Funnel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export function FunnelInsightDataExploration(): JSX.Element {
    const { insightLoading, insightProps } = useValues(insightLogic)
    const { isFunnelWithEnoughSteps, hasFunnelResults } = useValues(funnelDataLogic(insightProps))

    const nonEmptyState = (hasFunnelResults && isFunnelWithEnoughSteps) || insightLoading

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state': nonEmptyState,
            })}
        >
            <FunnelDataExploration />
        </div>
    )
}

export function FunnelInsight(): JSX.Element {
    const { insightProps, insightLoading } = useValues(insightLogic)
    const { hasFunnelResults, isFunnelWithEnoughSteps } = useValues(funnelLogic(insightProps))
    const nonEmptyState = (hasFunnelResults && isFunnelWithEnoughSteps) || insightLoading

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
