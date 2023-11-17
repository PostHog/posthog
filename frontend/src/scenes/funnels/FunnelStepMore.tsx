import { FunnelPathType, PathType, InsightType } from '~/types'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { funnelDataLogic } from './funnelDataLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

type FunnelStepMoreProps = {
    stepIndex: number
}

export function FunnelStepMore({ stepIndex }: FunnelStepMoreProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))

    const filterProps = cleanFilters(queryNodeToFilter(querySource!))

    const aggregationGroupTypeIndex = querySource?.aggregation_group_type_index

    // Don't show paths modal if aggregating by groups - paths is user-based!
    if (aggregationGroupTypeIndex != undefined) {
        return null
    }

    const stepNumber = stepIndex + 1
    return (
        <More
            placement="bottom-start"
            noPadding
            overlay={
                <>
                    {stepNumber > 1 && (
                        <LemonButton
                            status="stealth"
                            fullWidth
                            to={urls.insightNew({
                                funnel_filter: { ...filterProps, funnel_step: stepNumber },
                                insight: InsightType.PATHS,
                                funnel_paths: FunnelPathType.before,
                                date_from: filterProps.date_from,
                                include_event_types: [PathType.PageView, PathType.CustomEvent],
                            })}
                        >
                            Show user paths leading to step
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton
                            status="stealth"
                            fullWidth
                            to={urls.insightNew({
                                funnel_filter: { ...filterProps, funnel_step: stepNumber },
                                insight: InsightType.PATHS,
                                funnel_paths: FunnelPathType.between,
                                date_from: filterProps.date_from,
                                include_event_types: [PathType.PageView, PathType.CustomEvent],
                            })}
                        >
                            Show user paths between previous step and this step
                        </LemonButton>
                    )}
                    <LemonButton
                        status="stealth"
                        fullWidth
                        to={urls.insightNew({
                            funnel_filter: { ...filterProps, funnel_step: stepNumber },
                            insight: InsightType.PATHS,
                            funnel_paths: FunnelPathType.after,
                            date_from: filterProps.date_from,
                            include_event_types: [PathType.PageView, PathType.CustomEvent],
                        })}
                    >
                        Show user paths after step
                    </LemonButton>
                    {stepNumber > 1 && (
                        <LemonButton
                            status="stealth"
                            fullWidth
                            to={urls.insightNew({
                                funnel_filter: { ...filterProps, funnel_step: stepNumber * -1 },
                                insight: InsightType.PATHS,
                                funnel_paths: FunnelPathType.after,
                                date_from: filterProps.date_from,
                                include_event_types: [PathType.PageView, PathType.CustomEvent],
                            })}
                        >
                            Show user paths after dropoff
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton
                            status="stealth"
                            fullWidth
                            to={urls.insightNew({
                                funnel_filter: { ...filterProps, funnel_step: stepNumber * -1 },
                                insight: InsightType.PATHS,
                                funnel_paths: FunnelPathType.before,
                                date_from: filterProps.date_from,
                                include_event_types: [PathType.PageView, PathType.CustomEvent],
                            })}
                        >
                            Show user paths before dropoff
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
