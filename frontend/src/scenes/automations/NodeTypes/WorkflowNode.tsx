import { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'

import './NodeTypes.scss'
import { AnyAutomationStep } from '../schema'
import { automationStepConfigLogic, kindToConfig } from '../AutomationStepSidebar/automationStepConfigLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { isAutomationEventSourceStep, isAutomationWebhookDestinationStep } from '../utils'
import { useActions, useValues } from 'kea'

const renderBodyForStep = (step: AnyAutomationStep): React.ReactNode => {
    if (isAutomationEventSourceStep(step)) {
        if (!step.filters || step.filters.length === 0) {
            return <span className="italic">Not setup.</span>
        }

        return (
            <div className="">
                {step.filters.map((f) => (
                    <div className="mb-1">
                        <span className="mr-1">Triggers on</span>
                        <PropertyKeyInfo
                            className="p-1 bg-primary-highlight rounded-sm"
                            value={f.name}
                            disablePopover
                        />
                    </div>
                ))}
            </div>
        )
    } else if (isAutomationWebhookDestinationStep(step)) {
        return 'webhook'
    }

    return 'other node'
}

const WorkflowNode = ({ id, data }: NodeProps<AnyAutomationStep>): JSX.Element => {
    const { activeStepId } = useValues(automationStepConfigLogic)
    const { setActiveStepId } = useActions(automationStepConfigLogic)

    const isActive = activeStepId && activeStepId === id

    const onClick = () => {
        if (isActive) {
            setActiveStepId(null)
        } else {
            setActiveStepId(id)
        }
    }

    return (
        <div
            onClick={onClick}
            title="click to add a child node"
            className={`bg-white pt-4 pb-5 px-5 w-60 cursor-pointer rounded-sm border ${
                isActive ? 'border-primary' : 'border-white'
            }`}
        >
            <div className="font-medium border-b border-primary-highlight pb-1 mb-2">
                <span className="mr-1 text-primary-light">{kindToConfig[data.kind].icon}</span>
                <span>{kindToConfig[data.kind].label}</span>
            </div>
            {renderBodyForStep(data)}
            <Handle className="handle" type="target" position={Position.Top} isConnectable={false} />
            <Handle className="handle" type="source" position={Position.Bottom} isConnectable={false} />
        </div>
    )
}

export default memo(WorkflowNode)
