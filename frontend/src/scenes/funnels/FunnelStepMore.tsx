import { useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { FunnelPathType, PathType } from '~/types'

import { funnelDataLogic } from './funnelDataLogic'

type FunnelStepMoreProps = {
    stepIndex: number
}

export function FunnelStepMore({ stepIndex }: FunnelStepMoreProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))

    const stepNumber = stepIndex + 1
    const getPathUrl = useCallback(
        (funnelPathType: FunnelPathType, dropOff = false): string => {
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.PathsQuery,
                    funnelPathsFilter: {
                        funnelStep: dropOff ? stepNumber * -1 : stepNumber,
                        funnelSource: querySource!,
                        funnelPathType,
                    },
                    pathsFilter: {
                        includeEventTypes: [PathType.PageView, PathType.CustomEvent],
                    },
                    dateRange: {
                        date_from: querySource?.dateRange?.date_from,
                    },
                },
            }

            return urls.insightNew({ query })
        },
        [querySource, stepNumber]
    )

    // Don't show paths modal if aggregating by groups - paths is user-based!
    if (querySource?.aggregation_group_type_index != undefined) {
        return null
    }

    return (
        <More
            placement="bottom-start"
            noPadding
            overlay={
                <>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.before)} targetBlank>
                            Show user paths leading to step
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.between)} targetBlank>
                            Show user paths between previous step and this step
                        </LemonButton>
                    )}
                    <LemonButton fullWidth to={getPathUrl(FunnelPathType.after)} targetBlank>
                        Show user paths after step
                    </LemonButton>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.after, true)} targetBlank>
                            Show user paths after dropoff
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.before, true)} targetBlank>
                            Show user paths before dropoff
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
