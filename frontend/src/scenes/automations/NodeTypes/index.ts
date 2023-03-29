import { NodeTypes } from 'reactflow'

import PlaceholderNode from './PlaceholderNode'
import WorkflowNode from './WorkflowNode'

// two different node types are needed for our example: workflow and placeholder nodes
const nodeTypes: NodeTypes = {
    placeholder: PlaceholderNode,
    workflow: WorkflowNode,
}

export default nodeTypes
