import React from 'react'
import { FunnelPathType, PathType, InsightType, AvailableFeature } from '~/types'
import { funnelLogic } from './funnelLogic'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { urls } from 'scenes/urls'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'

export function FunnelStepDropdownSideAction({ stepIndex }: { stepIndex: number }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { propertiesForUrl: filterProps, filters } = useValues(logic)
    const { user } = useValues(userLogic)

    if (!user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)) {
        // TODO: Consider showing the options but disabled with a prompt to upgrade
        return null
    }

    // Don't show paths modal if aggregating by groups - paths is user-based!
    if (filters.aggregation_group_type_index != undefined) {
        return null
    }

    const stepNumber = stepIndex + 1
    return (
        <More
            overlay={
                <>
                    {stepNumber > 1 && (
                        <LemonButton
                            type="stealth"
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
                            type="stealth"
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
                        type="stealth"
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
                            type="stealth"
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
                            type="stealth"
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
