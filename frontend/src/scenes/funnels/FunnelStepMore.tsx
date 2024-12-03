import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema'
import { FunnelPathType, PathType } from '~/types'

import { funnelDataLogic } from './funnelDataLogic'

type FunnelStepMoreProps = {
    stepIndex: number
}

export function FunnelStepMore({ stepIndex }: FunnelStepMoreProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))

    const aggregationGroupTypeIndex = querySource?.aggregation_group_type_index

    // Don't show paths modal if aggregating by groups - paths is user-based!
    if (aggregationGroupTypeIndex != undefined) {
        return null
    }

    const stepNumber = stepIndex + 1
    const getPathUrl = (funnelPathType: FunnelPathType, dropOff = false): string => {
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

        return urls.insightNew(undefined, undefined, query)
    }

    return (
        <More
            placement="bottom-start"
            noPadding
            overlay={
                <>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.before)}>
                            Show user paths leading to step
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.between)}>
                            Show user paths between previous step and this step
                        </LemonButton>
                    )}
                    <LemonButton fullWidth to={getPathUrl(FunnelPathType.after)}>
                        Show user paths after step
                    </LemonButton>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.after, true)}>
                            Show user paths after dropoff
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth to={getPathUrl(FunnelPathType.before, true)}>
                            Show user paths before dropoff
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
