import { kea, path, reducers } from 'kea'

import { Edge, Node } from 'reactflow'

import type { automationsLogicType } from './automationsLogicType'

const defaultSteps: Node[] = [
    {
        id: '1',
        data: { label: '🌮 Taco' },
        position: { x: 0, y: 0 },
        type: 'workflow',
    },
    {
        id: '2',
        data: { label: '+' },
        position: { x: 0, y: 150 },
        type: 'placeholder',
    },
]

const defaultEdges: Edge[] = [
    {
        id: '1=>2',
        source: '1',
        target: '2',
        type: 'placeholder',
    },
]

export const automationsLogic = kea<automationsLogicType>([
    path(['scenes', 'automations', 'automationsLogic']),
    reducers({
        steps: [
            defaultSteps,
            {
                setSteps: (state, { steps }) => steps,
            },
        ],
        edges: [
            defaultEdges,
            {
                setEdges: (state, { edges }) => edges,
            },
        ],
    }),
])
