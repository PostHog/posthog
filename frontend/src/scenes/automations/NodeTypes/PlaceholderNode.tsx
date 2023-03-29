import React, { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import cx from 'classnames'

import './NodeTypes.scss'
import usePlaceholderClick from '../hooks/usePlaceholderClick'

const PlaceholderNode = ({ id }: NodeProps): JSX.Element => {
    // see the hook implementation for details of the click handler
    // calling onClick turns this node and the connecting edge into a workflow node
    const onClick = usePlaceholderClick(id)

    const nodeClasses = cx(['node', 'placeholder'])

    return (
        <div style={{ width: 160 }}>
            <div
                onClick={onClick}
                className={nodeClasses}
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
