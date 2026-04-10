import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DEFAULT_QUERY } from 'scenes/notebooks/Nodes/NotebookNodeQuery'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { CustomerProfileScope, GroupTypeIndex } from '~/types'

import { customerProfileConfigLogic } from './customerProfileConfigLogic'
import type { customerProfileLogicType } from './customerProfileLogicType'

export const DEFAULT_PERSON_PROFILE_SIDEBAR: JSONContent[] = [
    { type: NotebookNodeType.Person, attrs: { title: 'Info' } },
    // FIXME: Map bg image is broken
    // { type: NotebookNodeType.Map, attrs: { title: 'Map' } },
    { type: NotebookNodeType.RelatedGroups, attrs: { title: 'Related groups' } },
    { type: NotebookNodeType.PersonProperties, attrs: { title: 'Properties' } },
]

export const DEFAULT_PERSON_PROFILE_CONTENT: JSONContent[] = [
    { type: NotebookNodeType.UsageMetrics, index: 0, attrs: { title: 'Usage metrics' } },
    { type: NotebookNodeType.CustomerJourney, index: 1, attrs: { title: 'Customer journey' } },
    { type: NotebookNodeType.PersonFeed, index: 2, attrs: { title: 'Session feed' } },
    { type: NotebookNodeType.LLMTrace, index: 3, attrs: { title: 'LLM traces' } },
    { type: NotebookNodeType.ZendeskTickets, index: 4, attrs: { title: 'Zendesk tickets' } },
    { type: NotebookNodeType.Issues, index: 5, attrs: { title: 'Issues' } },
    { type: NotebookNodeType.SupportTickets, index: 6, attrs: { title: 'Support tickets' } },
]

export const DEFAULT_GROUP_PROFILE_SIDEBAR: JSONContent[] = [
    { type: NotebookNodeType.Group, attrs: { title: 'Info' } },
    { type: NotebookNodeType.RelatedGroups, attrs: { title: 'Related people', type: 'person' } },
    { type: NotebookNodeType.GroupProperties, attrs: { title: 'Properties' } },
]

export const DEFAULT_GROUP_PROFILE_CONTENT: JSONContent[] = [
    { type: NotebookNodeType.UsageMetrics, index: 0, attrs: { title: 'Usage metrics' } },
    { type: NotebookNodeType.CustomerJourney, index: 1, attrs: { title: 'Customer journey' } },
    { type: NotebookNodeType.Query, index: 2, attrs: { title: 'Events' } },
    { type: NotebookNodeType.LLMTrace, index: 3, attrs: { title: 'LLM traces' } },
    { type: NotebookNodeType.ZendeskTickets, index: 4, attrs: { title: 'Zendesk tickets' } },
    { type: NotebookNodeType.Issues, index: 5, attrs: { title: 'Issues' } },
]

export type CustomerProfileAttrs = {
    personId?: string | undefined
    distinctIds?: string[]
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
                s.featureFlags,
                (_, props) => props.scope,
                (_, props) => props.attrs,
            ],
            (scopedSidebarContent, scopedAddAttrFunction, featureFlags, scope, attrs) => {
                const isJourneysEnabled = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]
                const isSupportEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT]
                const scopedDefaultContent = (
                    scope === CustomerProfileScope.PERSON
                        ? DEFAULT_PERSON_PROFILE_CONTENT
                        : DEFAULT_GROUP_PROFILE_CONTENT
                ).filter(
                    (node) =>
                        (node.type !== NotebookNodeType.CustomerJourney || isJourneysEnabled) &&
                        (node.type !== NotebookNodeType.SupportTickets || isSupportEnabled)
                )

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
    const distinctId = attrs?.distinctIds?.[0]
    const nodeId = `${node.type}-${personId}`

    switch (node.type) {
        case NotebookNodeType.UsageMetrics:
        case NotebookNodeType.LLMTrace:
        case NotebookNodeType.CustomerJourney:
        case NotebookNodeType.ZendeskTickets:
        case NotebookNodeType.Issues:
            return {
                ...node,
                attrs: { ...node.attrs, nodeId, personId, children },
            }
        case NotebookNodeType.SupportTickets:
            return {
                ...node,
                attrs: { ...node.attrs, nodeId, personId, distinctIds: attrs?.distinctIds, children },
            }
        case NotebookNodeType.PersonFeed:
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
        case NotebookNodeType.Person:
        case NotebookNodeType.PersonProperties:
            return {
                ...node,
                attrs: { ...node.attrs, nodeId, id: personId, distinctId, children },
            }
        case NotebookNodeType.RelatedGroups:
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
        case NotebookNodeType.UsageMetrics:
        case NotebookNodeType.LLMTrace:
        case NotebookNodeType.CustomerJourney:
        case NotebookNodeType.Issues:
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
        case NotebookNodeType.ZendeskTickets:
            return {
                ...node,
                attrs: { ...node.attrs, nodeId, groupKey, children },
            }
        case NotebookNodeType.Group:
        case NotebookNodeType.RelatedGroups:
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                    id: groupKey,
                    type: 'person',
                    groupTypeIndex,
                    children,
                },
            }
        case NotebookNodeType.GroupProperties:
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                },
            }
        case NotebookNodeType.Query:
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    query: {
                        ...DEFAULT_QUERY,
                        contextKey: 'group-profile-events',
                        showTableViews: true,
                        embedded: true,
                    },
                },
                nodeId,
                children,
            }

        default:
            return {
                ...node,
                attrs: {
                    ...node.attrs,
                    nodeId,
                    children,
                },
            }
    }
}
