import { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'

import './NodeTypes.scss'
import useNodeClickHandler from '../hooks/useNodeClick'
import { AnyAutomationStep, AutomationStepKind } from '../schema'
import { kindToConfig } from '../AutomationStepSidebar/automationStepConfigLogic'

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
        <div onClick={onClick} className="bg-white p-3 w-60" title="click to add a child node">
            <div className="font-medium border-b border-primary-highlight pb-1 mb-2">
                <span className="mr-0.5 text-primary-light">{kindToConfig[data.kind].icon}</span>{' '}
                <span>{kindToConfig[data.kind].label}</span>
            </div>
            <div>{summarizeWorflowStep(data)}</div>
            <Handle className="handle" type="target" position={Position.Top} isConnectable={false} />
            <Handle className="handle" type="source" position={Position.Bottom} isConnectable={false} />
        </div>
    )
}

export default memo(WorkflowNode)
