import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DEFAULT_QUERY } from 'scenes/notebooks/Nodes/NotebookNodeQuery'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { teamLogic } from 'scenes/teamLogic'

import { CustomerProfileScope, GroupTypeIndex } from '~/types'

import { sourceManagementLogic } from 'products/data_warehouse/frontend/shared/logics/sourceManagementLogic'

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
    { type: NotebookNodeType.SupportTickets, index: 4, attrs: { title: 'Support tickets' } },
    { type: NotebookNodeType.ZendeskTickets, index: 5, attrs: { title: 'Zendesk tickets' } },
    { type: NotebookNodeType.Issues, index: 6, attrs: { title: 'Issues' } },
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

interface PanelAvailability {
    isJourneysEnabled: boolean
    isSupportEnabled: boolean
    hasZendeskSource: boolean
    dataWarehouseSourcesLoading: boolean
}

// Panels backed by a product or warehouse source that may not be set up must be filtered out of
// *every* content path — defaults and saved configs alike — so we never render a live query
// against tables that don't exist (e.g. the Zendesk panel with no Zendesk warehouse source).
// Keeping this in one helper means any future entry point that builds profile content stays safe.
function filterAvailablePanels(
    nodes: JSONContent[],
    { isJourneysEnabled, isSupportEnabled, hasZendeskSource, dataWarehouseSourcesLoading }: PanelAvailability
): JSONContent[] {
    return (
        nodes
            .filter((node) => node.type !== NotebookNodeType.CustomerJourney || isJourneysEnabled)
            // Hide the Zendesk panel unless a Zendesk warehouse source exists — without one its
            // query targets non-existent zendesk_* tables.
            .filter((node) => node.type !== NotebookNodeType.ZendeskTickets || hasZendeskSource)
            // Support panel: show the table when support is on; when it's off, show the "set up
            // support" prompt only if there's no Zendesk either (don't nag teams that already use
            // Zendesk). Wait for sources to load before deciding, so we never flash the prompt at
            // a Zendesk team.
            .filter(
                (node) =>
                    node.type !== NotebookNodeType.SupportTickets ||
                    isSupportEnabled ||
                    (!hasZendeskSource && !dataWarehouseSourcesLoading)
            )
    )
}

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
            sourceManagementLogic,
            ['hasZendeskSource', 'dataWarehouseSourcesLoading'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [
            customerProfileConfigLogic({ scope: props.scope }),
            ['createConfig', 'updateConfig', 'loadConfigsSuccess', 'updateConfigSuccess', 'createConfigSuccess'],
            notebookLogic({ shortId: props.canvasShortId, mode: 'canvas' }),
            ['setLocalContent'],
            sourceManagementLogic,
            ['loadSourcesSuccess'],
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
                s.hasZendeskSource,
                s.dataWarehouseSourcesLoading,
                s.currentTeam,
                (_, props) => props.scope,
                (_, props) => props.attrs,
            ],
            (
                scopedSidebarContent,
                scopedAddAttrFunction,
                featureFlags,
                hasZendeskSource,
                dataWarehouseSourcesLoading,
                currentTeam,
                scope,
                attrs
            ) => {
                const scopedDefaultContent = filterAvailablePanels(
                    scope === CustomerProfileScope.PERSON
                        ? DEFAULT_PERSON_PROFILE_CONTENT
                        : DEFAULT_GROUP_PROFILE_CONTENT,
                    {
                        isJourneysEnabled: !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS],
                        isSupportEnabled: !!currentTeam?.conversations_enabled,
                        hasZendeskSource,
                        dataWarehouseSourcesLoading,
                    }
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
                s.featureFlags,
                s.hasZendeskSource,
                s.dataWarehouseSourcesLoading,
                s.currentTeam,
                (_, props) => props.attrs,
            ],
            (
                customerProfileConfig,
                scopedAddAttrFunction,
                featureFlags,
                hasZendeskSource,
                dataWarehouseSourcesLoading,
                currentTeam,
                attrs
            ): JSONContent[] | null => {
                if (!customerProfileConfig) {
                    return null
                }

                // Saved configs bypass defaultContent, so apply the same availability filter here —
                // otherwise a previously-saved Zendesk/support panel would render against a product
                // or source that is no longer set up.
                // `content` is declared as Record<string, any> on the config type but is stored as a
                // node array; cast to its real shape for the shared filter.
                const availableContent = filterAvailablePanels(customerProfileConfig.content as JSONContent[], {
                    isJourneysEnabled: !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS],
                    isSupportEnabled: !!currentTeam?.conversations_enabled,
                    hasZendeskSource,
                    dataWarehouseSourcesLoading,
                })

                const sidebar = customerProfileConfig.sidebar.map((node: JSONContent) =>
                    scopedAddAttrFunction({ attrs, node })
                )
                return availableContent.map((node: JSONContent, index: number) => {
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
        // The source list loads asynchronously, so the initial mount sync can run before we
        // know whether a Zendesk source exists. Re-sync once it resolves so the Zendesk and
        // Support panels appear/disappear to match the actual source and support state.
        loadSourcesSuccess: () => {
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
