import { Handle, Position } from '@xyflow/react'
import React from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { PathFlowNodeData, PATH_NODE_HEIGHT, PATH_NODE_WIDTH } from './pathFlowUtils'

export const PathFlowNode = React.memo(function PathFlowNode({
    data,
    id,
}: {
    data: PathFlowNodeData
    id: string
}): JSX.Element {
    return (
        <div
            className="flex items-center rounded border border-border bg-bg-light px-2 text-xs"
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
        </div>
    )
})
