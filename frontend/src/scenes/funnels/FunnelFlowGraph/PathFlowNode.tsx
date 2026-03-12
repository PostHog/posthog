import { Handle, Position } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconCheckCircle, IconPlus, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { insightLogic } from 'scenes/insights/insightLogic'

import { journeyEditorLogic } from 'products/customer_analytics/frontend/components/CustomerJourneys/journeyEditorLogic'

import { funnelFlowGraphLogic } from './funnelFlowGraphLogic'
import { PathFlowNodeData, PATH_NODE_HEIGHT, PATH_NODE_WIDTH } from './pathFlowUtils'
import { usePathNodeAddability } from './usePathNodeAddability'

export interface PathFlowNodeProps {
    data: PathFlowNodeData
    id: string
}

export function PathFlowNodeShell({
    id,
    data,
    className,
    children,
}: PathFlowNodeProps & { className?: string; children?: React.ReactNode }): JSX.Element {
    return (
        <div
            className={className ?? 'flex items-center rounded border border-primary bg-bg-light px-2 text-xs'}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: PATH_NODE_WIDTH, height: PATH_NODE_HEIGHT }}
        >
            <Handle type="target" position={Position.Left} id={`${id}-target`} className="opacity-0" />
            <Handle type="source" position={Position.Right} id={`${id}-source`} className="opacity-0" />

            <Tooltip title={data.eventName}>
                <span className="truncate flex-1">{data.displayName}</span>
            </Tooltip>
            <span className="ml-1 shrink-0 rounded bg-fill-highlight-100 px-1 text-muted text-xxs font-medium">
                {data.count}
            </span>

            {children}
        </div>
    )
}

export const PathFlowNode = React.memo(function PathFlowNode({ data, id }: PathFlowNodeProps): JSX.Element {
    const addable = usePathNodeAddability()

    const { insightProps } = useValues(insightLogic)
    const { expandedPath, funnelNodes } = useValues(funnelFlowGraphLogic(insightProps))

    const { stagedNodeIds, stagedNodeOptionalMap } = useValues(journeyEditorLogic)
    const { stagePathNode, unstagePathNode, toggleStagedNodeOptional } = useActions(journeyEditorLogic)

    const isStaged = stagedNodeIds.has(id)
    const isOptional = stagedNodeOptionalMap.get(id) ?? false
    const showAddButton = addable && !isStaged

    return (
        <PathFlowNodeShell
            id={id}
            data={data}
            className={`flex items-center rounded border px-2 text-xs ${
                isStaged
                    ? isOptional
                        ? 'border-dashed border-success bg-success-highlight'
                        : 'border-success bg-success-highlight'
                    : 'border-primary bg-bg-light'
            }`}
        >
            {showAddButton && expandedPath && (
                <LemonButton
                    size="xsmall"
                    icon={<IconPlus />}
                    className="ml-1 shrink-0"
                    onClick={() => stagePathNode(id, data.eventName, expandedPath, funnelNodes.length)}
                    tooltip="Add as funnel step"
                />
            )}
            {isStaged && (
                <>
                    <More
                        size="xsmall"
                        className="ml-1 shrink-0"
                        overlay={
                            <LemonButton
                                fullWidth
                                icon={<IconCheckCircle />}
                                onClick={() => toggleStagedNodeOptional(id)}
                            >
                                {isOptional ? 'Make required' : 'Make optional'}
                            </LemonButton>
                        }
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        className="shrink-0"
                        status="danger"
                        onClick={() => unstagePathNode(id)}
                        tooltip="Remove from staged steps"
                    />
                </>
            )}
        </PathFlowNodeShell>
    )
})
