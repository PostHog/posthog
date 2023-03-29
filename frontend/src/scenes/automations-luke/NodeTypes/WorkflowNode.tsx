import React, { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import cx from 'classnames'

import styles from './NodeTypes.module.css'
import useNodeClickHandler from '../hooks/useNodeClick'

const WorkflowNode = ({ id, data }: NodeProps): JSX.Element => {
    // see the hook implementation for details of the click handler
    // calling onClick adds a child node to this node
    const onClick = useNodeClickHandler(id)

    return (
        <div onClick={onClick} className={cx(styles.node)} title="click to add a child node">
            {data.label}
            <Handle className={styles.handle} type="target" position={Position.Top} isConnectable={false} />
            <Handle className={styles.handle} type="source" position={Position.Bottom} isConnectable={false} />
        </div>
    )
}

export default memo(WorkflowNode)
