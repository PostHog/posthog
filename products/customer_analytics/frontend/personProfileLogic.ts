import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { CustomerProfileScope } from '~/types'

import { customerProfileConfigLogic } from './customerProfileConfigLogic'
import type { personProfileLogicType } from './personProfileLogicType'

export const DEFAULT_PERSON_PROFILE_SIDEBAR: JSONContent[] = [
    { type: 'ph-person', title: 'Info' },
    // FIXME: Map bg image is broken
    // { type: 'ph-map', title: 'Map' },
    { type: 'ph-person-properties', title: 'Properties' },
    { type: 'ph-related-groups', title: 'Related groups' },
]

export const DEFAULT_PERSON_PROFILE_CONTENT: JSONContent[] = [
    { type: 'ph-usage-metrics', title: 'Usage metrics', index: 0 },
    { type: 'ph-person-feed', title: 'Session feed', index: 1 },
    { type: 'ph-llm-trace', title: 'LLM traces', index: 2 },
    { type: 'ph-zendesk-tickets', title: 'Zendesk tickets', index: 3 },
    { type: 'ph-issues', title: 'Issues', index: 4 },
]

export interface PersonProfileLogicProps {
    personId: string | undefined
    distinctId: string
}

export const personProfileLogic = kea<personProfileLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'personProfileLogic']),
    props({} as PersonProfileLogicProps),
    key(({ personId, distinctId }) => personId || distinctId),

    connect((props: PersonProfileLogicProps) => ({
        values: [
            customerProfileConfigLogic({ scope: CustomerProfileScope.PERSON }),
            ['personProfileConfig'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            customerProfileConfigLogic({ scope: CustomerProfileScope.PERSON }),
            ['createConfig', 'updateConfig', 'loadConfigsSuccess', 'updateConfigSuccess', 'createConfigSuccess'],
            notebookLogic({ shortId: `canvas-${props.personId}`, mode: 'canvas' }),
            ['setLocalContent'],
        ],
    })),

    actions({
        removeNode: (nodeType: string) => ({ nodeType }),
        addNode: (nodeType: string) => ({ nodeType }),
        resetToDefaults: true,
        setProfileLocalContent: (content: JSONContent[] | null) => ({ content }),
        saveChanges: true,
    }),

    reducers({
        profileLocalContent: [
            null as JSONContent[] | null,
            {
                setProfileLocalContent: (_, { content }) => content,
                resetToDefaults: () => null,
                saveChangesSuccess: () => null,
            },
        ],
    }),

    selectors({
        changed: [
            (s) => [s.profileLocalContent, s.storedContent],
            (profileLocalContent, storedContent) => {
                if (!profileLocalContent) {
                    return false
                }

                const profileLocalContentTypes = profileLocalContent?.map((node) => node.type).join()
                const defaultLocalContentTypes = DEFAULT_PERSON_PROFILE_CONTENT.map((node) => node.type).join()
                if (profileLocalContentTypes === defaultLocalContentTypes && !storedContent) {
                    return false
                }

                if (!storedContent) {
                    return true
                }

                const storedContentTypes = storedContent.map((node) => node.type).join()
                const hasChanged = profileLocalContentTypes !== storedContentTypes

                return hasChanged
            },
        ],
        isProfileConfigEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.CUSTOMER_PROFILE_CONFIG_BUTTON],
        ],
        storedContent: [
            (s) => [s.personProfileConfig, (_, props) => props.personId, (_, props) => props.distinctId],
            (personProfileConfig, personId, distinctId): JSONContent[] | null => {
                if (!personProfileConfig) {
                    return null
                }

                const sidebar = personProfileConfig.sidebar.map((node: JSONContent) =>
                    addPersonAttrsToNode({ node, personId, distinctId })
                )
                return personProfileConfig.content.map((node: JSONContent, index: number) => {
                    if (index === 0) {
                        return addPersonAttrsToNode({ node, personId, distinctId, children: sidebar })
                    }
                    return addPersonAttrsToNode({ node, personId, distinctId })
                })
            },
        ],
        content: [
            (s) => [
                s.storedContent,
                s.profileLocalContent,
                s.isProfileConfigEnabled,
                (_, props) => props.personId,
                (_, props) => props.distinctId,
            ],
            (storedContent, profileLocalContent, isProfileConfigEnabled, personId, distinctId): JSONContent[] => {
                // Return default content if flag is disabled
                if (isProfileConfigEnabled) {
                    if (profileLocalContent !== null) {
                        return profileLocalContent
                    }
                    if (storedContent !== null) {
                        return storedContent
                    }
                }

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

    listeners(({ actions, values, props }) => ({
        removeNode: ({ nodeType }) => {
            const currentContent = values.profileLocalContent || values.content
            const filteredContent = currentContent.filter((node) => node.type !== nodeType)
            actions.setProfileLocalContent(filteredContent)
            actions.setLocalContent(filteredContent, true)
        },
        addNode: ({ nodeType }) => {
            const currentContent = values.profileLocalContent || values.content
            const nodeToAdd = DEFAULT_PERSON_PROFILE_CONTENT.find((node) => node.type === nodeType)
            if (!nodeToAdd) {
                return
            }

            const newNode = addPersonAttrsToNode({
                node: nodeToAdd,
                personId: props.personId,
                distinctId: props.distinctId,
            })

            const updatedContent = [...currentContent, newNode].sort((a, b) => {
                const indexA = a.index ?? a.attrs?.index ?? 999
                const indexB = b.index ?? b.attrs?.index ?? 999
                return indexA - indexB
            })
            actions.setProfileLocalContent(updatedContent)
            actions.setLocalContent(updatedContent, true)
        },
        resetToDefaults: () => {
            actions.setProfileLocalContent(null)
            actions.setLocalContent(values.content, true)
        },
        saveChanges: async () => {
            if (!values.profileLocalContent || !values.changed) {
                return
            }

            const config = {
                scope: 'person' as const,
                content: values.profileLocalContent.map((node) => ({
                    type: node.type,
                    title: node.attrs?.title || node.title,
                    index: node.attrs?.index || node.index,
                })),
                sidebar: DEFAULT_PERSON_PROFILE_SIDEBAR,
            }

            if (values.personProfileConfig) {
                actions.updateConfig(values.personProfileConfig.id, config)
            } else {
                actions.createConfig(config)
            }
        },
        createConfigSuccess: () => {
            actions.setLocalContent(values.content, true)
            actions.resetToDefaults()
        },
        updateConfigSuccess: () => {
            actions.setLocalContent(values.content, true)
            actions.resetToDefaults()
        },
        loadConfigsSuccess: () => {
            actions.setLocalContent(values.content, true)
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.content) {
            actions.setLocalContent(values.content, true)
        }
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
                attrs: { personId, nodeId: uuid(), children, title: node.title, index: node.index },
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
                    index: node.index,
                },
            }
        case 'ph-person':
        case 'ph-person-properties':
            return {
                ...node,
                attrs: { id: personId, distinctId, nodeId: uuid(), children, title: node.title, index: node.index },
            }
        case 'ph-related-groups':
            return {
                ...node,
                attrs: { id: personId, nodeId: uuid(), type: 'group', children, title: node.title, index: node.index },
            }
        default:
            return node
    }
}
