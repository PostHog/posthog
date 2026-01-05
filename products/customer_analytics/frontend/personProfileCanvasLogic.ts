import { kea, key, path, props, selectors } from 'kea'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils'

import type { personProfileCanvasLogicType } from './personProfileCanvasLogicType'

export const DEFAULT_PERSON_PROFILE_SIDEBAR: JSONContent[] = [
    { type: 'ph-person', title: 'Info' },
    // FIXME: Map bg image is broken
    // { type: 'ph-map', title: 'Map' },
    { type: 'ph-person-properties', title: 'Properties' },
    { type: 'ph-related-groups', title: 'Related groups' },
]

export const DEFAULT_PERSON_PROFILE_CONTENT: JSONContent[] = [
    { type: 'ph-usage-metrics', title: 'Usage metrics' },
    { type: 'ph-person-feed', title: 'Session feed' },
    { type: 'ph-llm-trace', title: 'LLM traces' },
    { type: 'ph-zendesk-tickets', title: 'Zendesk tickets' },
    { type: 'ph-issues', title: 'Issues' },
]

export interface PersonProfileCanvasLogicProps {
    personId: string | undefined
    distinctId: string
}

export const personProfileCanvasLogic = kea<personProfileCanvasLogicType>([
    path(['products', 'customer_analytics', 'person_profile_canvas']),
    props({} as PersonProfileCanvasLogicProps),
    key(({ personId, distinctId }) => personId || distinctId),

    selectors({
        content: [
            () => [(_, props) => props.personId, (_, props) => props.distinctId],
            (personId, distinctId): JSONContent[] => {
                const sidebar = DEFAULT_PERSON_PROFILE_SIDEBAR.map((node) =>
                    addPersonAttrsToNode({ node, personId, distinctId })
                )
                return DEFAULT_PERSON_PROFILE_CONTENT.map((node, index) => {
                    if (index === 0) {
                        return addPersonAttrsToNode({ node, personId, distinctId, children: sidebar })
                    }
                    return addPersonAttrsToNode({ node, personId, distinctId })
                })
            },
        ],
    }),
])

export interface AddPersonAttrsToNodeProps {
    node: JSONContent
    personId: string | undefined
    distinctId: string
    children?: JSONContent[]
}

export function addPersonAttrsToNode({
    node,
    personId,
    distinctId,
    children = [],
}: AddPersonAttrsToNodeProps): JSONContent {
    switch (node.type) {
        case 'ph-usage-metrics':
        case 'ph-llm-trace':
        case 'ph-zendesk-tickets':
        case 'ph-issues':
            return {
                ...node,
                attrs: { personId, nodeId: uuid(), children, title: node.title },
            }
        case 'ph-person-feed':
            return {
                ...node,
                attrs: {
                    height: null,
                    id: personId,
                    distinctId,
                    nodeId: uuid(),
                    __init: null,
                    children,
                    title: node.title,
                },
            }
        case 'ph-person':
        case 'ph-person-properties':
            return {
                ...node,
                attrs: { id: personId, distinctId, nodeId: uuid(), children, title: node.title },
            }
        case 'ph-related-groups':
            return {
                ...node,
                attrs: { id: personId, nodeId: uuid(), type: 'group', children, title: node.title },
            }
        default:
            return node
    }
}
