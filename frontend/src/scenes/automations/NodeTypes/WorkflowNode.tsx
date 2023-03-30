import { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'

import './NodeTypes.scss'
import useNodeClickHandler from '../hooks/useNodeClick'
import { AnyAutomationStep, AutomationStepKind } from '../schema'

const summarizeWorflowStep = (step: AnyAutomationStep): string => {
    if (step.kind === AutomationStepKind.EventSource) {
        return 'event'
    } else if (step.kind === AutomationStepKind.WebhookDestination) {
        return 'webhook'
    }

    return 'other node'
}

const WorkflowNode = ({ id, data }: NodeProps<AnyAutomationStep>): JSX.Element => {
    // see the hook implementation for details of the click handler
    // calling onClick adds a child node to this node
    const onClick = useNodeClickHandler(id)

    return (
        <div onClick={onClick} className="node" title="click to add a child node">
            {summarizeWorflowStep(data)}
            <Handle className="handle" type="target" position={Position.Top} isConnectable={false} />
            <Handle className="handle" type="source" position={Position.Bottom} isConnectable={false} />
        </div>
    )
}

export default memo(WorkflowNode)
