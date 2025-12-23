import { kea, key, path, props, selectors } from 'kea'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils'

import type { personProfileCanvasLogicType } from './personProfileCanvasLogicType'

export const DEFAULT_PERSON_PROFILE_SIDEBAR: JSONContent[] = [
    { type: 'ph-person' },
    // FIXME: Map bg image is broken
    // { type: 'ph-map' },
    { type: 'ph-person-properties' },
    { type: 'ph-related-groups' },
]

export const DEFAULT_PERSON_PROFILE_CONTENT: JSONContent[] = [
    { type: 'ph-usage-metrics' },
    { type: 'ph-person-feed' },
    { type: 'ph-llm-trace' },
    { type: 'ph-zendesk-tickets' },
    { type: 'ph-issues' },
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
                attrs: { personId, nodeId: uuid(), children },
            }
        case 'ph-person-feed':
            return {
                ...node,
                attrs: { height: null, title: null, id: personId, distinctId, nodeId: uuid(), __init: null, children },
            }
        case 'ph-person':
            return {
                ...node,
                attrs: { id: personId, distinctId, nodeId: uuid(), title: 'Info', children },
            }
        case 'ph-person':
        case 'ph-person-properties':
            return {
                ...node,
                attrs: { id: personId, distinctId, nodeId: uuid(), children },
            }
        case 'ph-related-groups':
            return {
                ...node,
                attrs: { id: personId, nodeId: uuid(), type: 'group', children },
            }
        default:
            return node
    }
}
