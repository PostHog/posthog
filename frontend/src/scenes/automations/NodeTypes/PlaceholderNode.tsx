import React, { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import cx from 'classnames'

import './NodeTypes.scss'
import usePlaceholderClick from '../hooks/usePlaceholderClick'

const PlaceholderNode = ({ id, data }: NodeProps): JSX.Element => {
    // see the hook implementation for details of the click handler
    // calling onClick turns this node and the connecting edge into a workflow node
    const onClick = usePlaceholderClick(id)

    const nodeClasses = cx(['node', 'placeholder'])

    return (
        <div onClick={onClick} className={nodeClasses} title="click to add a node">
            {data.label}
            <Handle className={'handle'} type="target" position={Position.Top} isConnectable={false} />
            <Handle className={'handle'} type="source" position={Position.Bottom} isConnectable={false} />
        </div>
    )
}

export default memo(PlaceholderNode)
