import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { CustomerProfileScope, GroupTypeIndex } from '~/types'

import { customerProfileConfigLogic } from './customerProfileConfigLogic'
import type { customerProfileLogicType } from './customerProfileLogicType'

export const DEFAULT_PERSON_PROFILE_SIDEBAR: JSONContent[] = [
    { type: 'ph-person', attrs: { title: 'Info' } },
    // FIXME: Map bg image is broken
    // { type: 'ph-map', attrs: { title: 'Map' } },
    { type: 'ph-person-properties', attrs: { title: 'Properties' } },
    { type: 'ph-related-groups', attrs: { title: 'Related groups' } },
]

export const DEFAULT_PERSON_PROFILE_CONTENT: JSONContent[] = [
    { type: 'ph-usage-metrics', index: 0, attrs: { title: 'Usage metrics' } },
    { type: 'ph-person-feed', index: 1, attrs: { title: 'Session feed' } },
    { type: 'ph-llm-trace', index: 2, attrs: { title: 'LLM traces' } },
    { type: 'ph-zendesk-tickets', index: 3, attrs: { title: 'Zendesk tickets' } },
    { type: 'ph-issues', index: 4, attrs: { title: 'Issues' } },
]

export const DEFAULT_GROUP_PROFILE_SIDEBAR: JSONContent[] = [
    { type: 'ph-group', attrs: { title: 'Info' } },
    { type: 'ph-group-properties', attrs: { title: 'Properties' } },
    { type: 'ph-related-groups', attrs: { title: 'Related people', type: 'person' } },
]

export const DEFAULT_GROUP_PROFILE_CONTENT: JSONContent[] = [
    { type: 'ph-usage-metrics', index: 0, attrs: { title: 'Usage metrics' } },
    { type: 'ph-llm-trace', index: 1, attrs: { title: 'LLM traces' } },
    { type: 'ph-zendesk-tickets', index: 2, attrs: { title: 'Zendesk tickets' } },
    { type: 'ph-issues', index: 3, attrs: { title: 'Issues' } },
]

export type CustomerProfileAttrs = {
    personId?: string | undefined
    distinctId?: string
    groupKey?: string
    groupTypeIndex?: GroupTypeIndex
}

export interface PersonProfileLogicProps {
    scope: CustomerProfileScope
    attrs: CustomerProfileAttrs
    key: string
    canvasShortId: string
}

export const customerProfileLogic = kea<customerProfileLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'customerProfileLogic']),
    props({} as PersonProfileLogicProps),
    key(({ key }) => key),

    connect((props: PersonProfileLogicProps) => ({
        values: [
            customerProfileConfigLogic({ scope: props.scope }),
            ['customerProfileConfig'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            customerProfileConfigLogic({ scope: props.scope }),
            ['createConfig', 'updateConfig', 'loadConfigsSuccess', 'updateConfigSuccess', 'createConfigSuccess'],
            notebookLogic({ shortId: props.canvasShortId, mode: 'canvas' }),
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
            (s) => [s.profileLocalContent, s.storedContent, s.defaultContent],
            (profileLocalContent, storedContent, defaultContent) => {
                if (!profileLocalContent) {
                    return false
                }

                const profileLocalContentTypes = profileLocalContent?.map((node) => node.type).join()
                const defaultLocalContentTypes = defaultContent.map((node) => node.type).join()
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
        scopedSidebarContent: [
            () => [(_, props) => props.scope],
            (scope) =>
                scope === CustomerProfileScope.PERSON ? DEFAULT_PERSON_PROFILE_SIDEBAR : DEFAULT_GROUP_PROFILE_SIDEBAR,
        ],
        scopedAddAttrFunction: [
            () => [(_, props) => props.scope],
            (scope) => (scope === CustomerProfileScope.PERSON ? addPersonAttrsToNode : addGroupAttrsToNode),
        ],
        defaultContent: [
            (s) => [
                s.scopedSidebarContent,
                s.scopedAddAttrFunction,
                (_, props) => props.scope,
                (_, props) => props.attrs,
            ],
            (scopedSidebarContent, scopedAddAttrFunction, scope, attrs) => {
                const scopedDefaultContent =
                    scope === CustomerProfileScope.PERSON
                        ? DEFAULT_PERSON_PROFILE_CONTENT
                        : DEFAULT_GROUP_PROFILE_CONTENT

                const sidebar = scopedSidebarContent.map((node) => scopedAddAttrFunction({ attrs, node }))
                return scopedDefaultContent.map((node, index) => {
                    if (index === 0) {
                        return scopedAddAttrFunction({ attrs, node, children: sidebar })
                    }
                    return scopedAddAttrFunction({ attrs, node })
                })
            },
        ],
        storedContent: [
            (s) => [
                s.customerProfileConfig,
                s.scopedAddAttrFunction,
                (_, props) => props.attrs,
                (_, props) => props.scope,
            ],
            (customerProfileConfig, scopedAddAttrFunction, attrs): JSONContent[] | null => {
                if (!customerProfileConfig) {
                    return null
                }

                const sidebar = customerProfileConfig.sidebar.map((node: JSONContent) =>
                    scopedAddAttrFunction({ attrs, node })
                )
                return customerProfileConfig.content.map((node: JSONContent, index: number) => {
                    if (index === 0) {
                        return scopedAddAttrFunction({ attrs, node, children: sidebar })
                    }
                    return scopedAddAttrFunction({ attrs, node })
                })
            },
        ],
        content: [
            (s) => [s.defaultContent, s.storedContent, s.profileLocalContent, s.isProfileConfigEnabled],
            (defaultContent, storedContent, profileLocalContent, isProfileConfigEnabled): JSONContent[] => {
                // Return default content if flag is disabled
                if (isProfileConfigEnabled) {
                    if (profileLocalContent !== null) {
                        return profileLocalContent
                    }
                    if (storedContent !== null) {
                        return storedContent
                    }
                }
                return defaultContent
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
            const nodeToAdd = values.defaultContent.find((node) => node.type === nodeType)
            if (!nodeToAdd) {
                return
            }

            const updatedContent = [...currentContent, nodeToAdd].sort((a, b) => {
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
                scope: props.scope,
                content: values.profileLocalContent.map((node) => ({
                    type: node.type,
                    title: node.attrs?.title || node.title,
                    index: node.attrs?.index || node.index,
                })),
                sidebar: values.scopedSidebarContent,
            }

            if (values.customerProfileConfig) {
                actions.updateConfig(values.customerProfileConfig.id, config)
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

export interface AddAttrsToNodeProps {
    attrs: CustomerProfileAttrs
    node: JSONContent
    children?: JSONContent[]
}

export function addPersonAttrsToNode({ attrs, node, children = [] }: AddAttrsToNodeProps): JSONContent {
    const personId = attrs?.personId
    const distinctId = attrs?.distinctId
    const nodeId = `${node.type}-${personId}`

    switch (node.type) {
        case 'ph-usage-metrics':
        case 'ph-llm-trace':
        case 'ph-zendesk-tickets':
        case 'ph-issues':
            return {
                ...node,
                attrs: { ...node.attrs, nodeId, personId, children },
            }
        case 'ph-person-feed':
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                    height: null,
                    id: personId,
                    distinctId,
                    __init: null,
                    children,
                },
            }
        case 'ph-person':
        case 'ph-person-properties':
            return {
                ...node,
                attrs: { ...node.attrs, nodeId, id: personId, distinctId, children },
            }
        case 'ph-related-groups':
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                    id: personId,
                    type: 'group',
                    children,
                },
            }
        default:
            return node
    }
}

export function addGroupAttrsToNode({ attrs, node, children = [] }: AddAttrsToNodeProps): JSONContent {
    const groupKey = attrs?.groupKey
    const groupTypeIndex = attrs?.groupTypeIndex
    const nodeId = `${node.type}-${groupKey}-${groupTypeIndex}`

    switch (node.type) {
        case 'ph-usage-metrics':
        case 'ph-llm-trace':
        case 'ph-issues':
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                    groupKey,
                    groupTypeIndex,
                    children,
                },
            }
        case 'ph-zendesk-tickets':
            return {
                ...node,
                attrs: { ...node.attrs, nodeId, groupKey, children },
            }
        case 'ph-group':
        case 'ph-related-groups':
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                    id: groupKey,
                    groupTypeIndex,
                    children,
                },
            }
        case 'ph-group-properties':
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                },
            }
        default:
            return node
    }
}
