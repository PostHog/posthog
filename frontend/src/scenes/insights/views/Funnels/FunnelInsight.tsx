import clsx from 'clsx'
import { useValues } from 'kea'
import { Funnel } from 'scenes/funnels/Funnel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function FunnelInsight(): JSX.Element {
    const { insightLoading, insightProps } = useValues(insightLogic)
    const { isFunnelWithEnoughSteps } = useValues(insightVizDataLogic(insightProps))
    const { hasFunnelResults } = useValues(funnelDataLogic(insightProps))

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
