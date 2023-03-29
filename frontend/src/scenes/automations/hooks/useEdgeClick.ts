import { uuid } from 'lib/utils'
import { EdgeProps, useReactFlow } from 'reactflow'

import { randomLabel } from '../utils'

// this hook implements the logic for clicking the button on a workflow edge
// on edge click: create a node in between the two nodes that are connected by the edge
function useEdgeClick(id: EdgeProps['id']): () => void {
    const { setEdges, setNodes, getNode, getEdge } = useReactFlow()

    const handleEdgeClick = (): void => {
        // first we retrieve the edge object to get the source and target id
        const edge = getEdge(id)

        if (!edge) {
            return
        }

        // we retrieve the target node to get its position
        const targetNode = getNode(edge.target)

        if (!targetNode) {
            return
        }

        // create a unique id for newly added elements
        const insertNodeId = uuid()

        // this is the node object that will be added in between source and target node
        const insertNode = {
            id: insertNodeId,
            // we place the node at the current position of the target (prevents jumping)
            position: { x: targetNode.position.x, y: targetNode.position.y },
            data: { label: randomLabel() },
            type: 'workflow',
        }

        // new connection from source to new node
        const sourceEdge = {
            id: `${edge.source}->${insertNodeId}`,
            source: edge.source,
            target: insertNodeId,
            type: 'workflow',
        }

        // new connection from new node to target
        const targetEdge = {
            id: `${insertNodeId}->${edge.target}`,
            source: insertNodeId,
            target: edge.target,
            type: 'workflow',
        }

        // remove the edge that was clicked as we have a new connection with a node inbetween
        setEdges((edges) => edges.filter((e) => e.id !== id).concat([sourceEdge, targetEdge]))

        // insert the node between the source and target node in the react flow state
        setNodes((nodes) => {
            const targetNodeIndex = nodes.findIndex((node) => node.id === edge.target)

            return [...nodes.slice(0, targetNodeIndex), insertNode, ...nodes.slice(targetNodeIndex, nodes.length)]
        })
    }

    return handleEdgeClick
}

export default useEdgeClick
