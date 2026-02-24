import { useActions, useValues } from 'kea'

import { IconCollapse } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelPathType } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPathsExpansionLogic } from './funnelPathsExpansionLogic'

type FunnelStepMoreFlowProps = {
    stepIndex: number
}

export function FunnelStepMoreFlow({ stepIndex }: FunnelStepMoreFlowProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))
    const { expandedPath, pathsLoading } = useValues(funnelPathsExpansionLogic(insightProps))
    const { expandPath, collapsePath } = useActions(funnelPathsExpansionLogic(insightProps))

    const stepNumber = stepIndex + 1

    if (querySource?.aggregation_group_type_index != undefined) {
        return null
    }

    const isActiveOnThisStep = expandedPath !== null && expandedPath.stepIndex === stepIndex

    const isActiveExpansion = (pathType: FunnelPathType, dropOff: boolean): boolean =>
        isActiveOnThisStep && expandedPath!.pathType === pathType && expandedPath!.dropOff === dropOff

    const handleClick = (pathType: FunnelPathType, dropOff: boolean): void => {
        if (isActiveExpansion(pathType, dropOff)) {
            collapsePath()
        } else {
            expandPath({ stepIndex, pathType, dropOff })
        }
    }

    if (isActiveOnThisStep) {
        return pathsLoading ? (
            <Spinner textColored className="text-lg" />
        ) : (
            <LemonButton size="xsmall" icon={<IconCollapse />} onClick={() => collapsePath()} />
        )
    }

    return (
        <More
            placement="bottom-start"
            noPadding
            overlay={
                <>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth onClick={() => handleClick(FunnelPathType.before, false)}>
                            Show paths leading to step
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth onClick={() => handleClick(FunnelPathType.between, false)}>
                            Show paths between previous step and this step
                        </LemonButton>
                    )}
                    <LemonButton fullWidth onClick={() => handleClick(FunnelPathType.after, false)}>
                        Show paths after step
                    </LemonButton>
                    {stepNumber > 1 && (
                        <LemonButton fullWidth onClick={() => handleClick(FunnelPathType.after, true)}>
                            Show paths after dropoff
                        </LemonButton>
                    )}
                    {stepNumber > 1 && (
                        <LemonButton fullWidth onClick={() => handleClick(FunnelPathType.before, true)}>
                            Show paths before dropoff
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
