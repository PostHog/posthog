import clsx from 'clsx'
import { useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelInsight(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isValidFunnel, insightLoading, areFiltersValid } = useValues(funnelLogic(insightProps))
    const nonEmptyState = (isValidFunnel && areFiltersValid) || insightLoading

    return (
        <>
            <div
                className={clsx('funnel-insights-container', {
                    'non-empty-state': nonEmptyState,
                })}
            >
                <Funnel />
            </div>
        </>
    )
}
