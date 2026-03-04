import { useActions, useValues } from 'kea'
import React from 'react'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { insightLogic } from 'scenes/insights/insightLogic'

import { journeyBuilderLogic } from 'products/customer_analytics/frontend/components/CustomerJourneys/journeyBuilderLogic'

import { funnelFlowGraphLogic } from './funnelFlowGraphLogic'
import { PathFlowNodeShell, PathFlowNodeProps } from './PathFlowNode'

export const BuilderPathFlowNode = React.memo(function BuilderPathFlowNode({
    id,
    data,
}: PathFlowNodeProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { expandedPath, funnelNodes } = useValues(funnelFlowGraphLogic(insightProps))
    const { collapsePath } = useActions(funnelFlowGraphLogic(insightProps))
    const { addStepFromPath } = useActions(journeyBuilderLogic)

    const addable = expandedPath !== null && !expandedPath.dropOff

    return (
        <PathFlowNodeShell id={id} data={data}>
            {addable && expandedPath && (
                <LemonButton
                    size="xsmall"
                    icon={<IconPlus />}
                    className="ml-1 shrink-0"
                    onClick={() => {
                        addStepFromPath(data.eventName, expandedPath, funnelNodes.length)
                        collapsePath()
                    }}
                    tooltip="Add as funnel step"
                />
            )}
        </PathFlowNodeShell>
    )
})
