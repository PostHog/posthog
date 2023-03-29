import { memo } from 'react'
import { Handle, Position } from 'reactflow'

import './NodeTypes.scss'
import { useActions } from 'kea'
import { automationStepMenuLogic } from '../AutomationStepSidebar/automationStepMenuLogic'

const PlaceholderNode = (): JSX.Element => {
    const { openMenu } = useActions(automationStepMenuLogic)

    return (
        <div style={{ width: 160 }}>
            <div
                onClick={openMenu}
                className="node placeholder"
                style={{
                    width: 40,
                    height: 40,
                    margin: 'auto',
                    borderRadius: 20,
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                }}
                title="click to add a node"
            >
                +
                <Handle className={'handle'} type="target" position={Position.Top} isConnectable={false} />
                <Handle className={'handle'} type="source" position={Position.Bottom} isConnectable={false} />
            </div>
        </div>
    )
}

export default memo(PlaceholderNode)
