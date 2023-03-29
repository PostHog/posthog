import { useCallback } from 'react'
import { NodeProps, useReactFlow, getOutgoers } from 'reactflow'

import { uuid, randomLabel } from '../utils'

// this hook implements the logic for clicking a workflow node
// on workflow node click: create a new child node of the clicked node
export function useNodeClick(id: NodeProps['id']): () => void {
    const { setEdges, setNodes, getNodes, getEdges, getNode } = useReactFlow()

    const onClick = useCallback(() => {
        // we need the parent node object for positioning the new child node
        const parentNode = getNode(id)

        if (!parentNode) {
            return
        }

        // create a unique id for the child node
        const childNodeId = uuid()

        // create a unique id for the placeholder (the placeholder gets added to the new child node)
        const childPlaceholderId = uuid()

        // create the child node
        const childNode = {
            id: childNodeId,
            // we try to place the child node close to the calculated position from the layout algorithm
            // 150 pixels below the parent node, this spacing can be adjusted in the useLayout hook
            position: { x: parentNode.position.x, y: parentNode.position.y + 150 },
            type: 'workflow',
            data: { label: randomLabel() },
        }

        // create a placeholder for the new child node
        // we want to display a placeholder for all workflow nodes that do not have a child already
        // as the newly created node will not have a child, it gets this placeholder
        const childPlaceholderNode = {
            id: childPlaceholderId,
            // we place the placeholder 150 pixels below the child node, spacing can be adjusted in the useLayout hook
            position: { x: childNode.position.x, y: childNode.position.y + 150 },
            type: 'placeholder',
            data: { label: '+' },
        }

        // we need to create a connection from parent to child
        const childEdge = {
            id: `${parentNode.id}=>${childNodeId}`,
            source: parentNode.id,
            target: childNodeId,
            type: 'workflow',
        }

        // we need to create a connection from child to our placeholder
        const childPlaceholderEdge = {
            id: `${childNodeId}=>${childPlaceholderId}`,
            source: childNodeId,
            target: childPlaceholderId,
            type: 'placeholder',
        }

        // if the clicked node has had any placeholders as children, we remove them because it will get a child now
        const existingPlaceholders = getOutgoers(parentNode, getNodes(), getEdges())
            .filter((node) => node.type === 'placeholder')
            .map((node) => node.id)

        // add the new nodes (child and placeholder), filter out the existing placeholder nodes of the clicked node
        setNodes((nodes) =>
            nodes.filter((node) => !existingPlaceholders.includes(node.id)).concat([childNode, childPlaceholderNode])
        )

        // add the new edges (node -> child, child -> placeholder), filter out any placeholder edges
        setEdges((edges) =>
            edges
                .filter((edge) => !existingPlaceholders.includes(edge.target))
                .concat([childEdge, childPlaceholderEdge])
        )
    }, [getEdges, getNode, getNodes, id, setEdges, setNodes])

    return onClick
}

export default useNodeClick
