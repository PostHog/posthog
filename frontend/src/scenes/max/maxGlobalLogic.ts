import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { AssistantContextualTool } from '~/queries/schema/schema-assistant-messages'

import type { maxGlobalLogicType } from './maxGlobalLogicType'

export interface ToolDefinition {
    /** A unique identifier for the tool */
    name: AssistantContextualTool
    /** A user-friendly display name for the tool */
    displayName: string
    /** Contextual data to be included for use by the LLM */
    context: Record<string, any>
    /**
     * Optional: If this tool is the main one of the page, you can override Max's default intro headline and description when it's mounted.
     *
     * Note that if more than one mounted tool has an intro override, only one will take effect.
     */
    introOverride?: {
        /** The default is something like "How can I help you build?" - stick true to this question form. */
        headline: string
        /** The default is "Ask me about your product and your users." */
        description: string
    }
    /** Optional: When in context, the tool can add items to the pool of Max's suggested questions */
    suggestions?: string[] // TODO: Suggestions aren't used yet, pending a refactor of maxLogic's allSuggestions
    /** The callback function that will be executed with the LLM's tool call output */
    callback: (toolOutput: any) => void
}

export const maxGlobalLogic = kea<maxGlobalLogicType>([
    path(['scenes', 'max', 'maxGlobalLogic']),
    connect(() => ({
        actions: [organizationLogic, ['updateOrganization']],
        values: [organizationLogic, ['currentOrganization']],
    })),
    actions({
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
        registerTool: (tool: ToolDefinition) => ({ tool }),
        deregisterTool: (key: string) => ({ key }),
    }),
    reducers({
        toolMap: [
            {} as Record<string, ToolDefinition>,
            {
                registerTool: (state, { tool }) => ({
                    ...state,
                    [tool.name]: tool,
                }),
                deregisterTool: (state, { key }) => {
                    const newState = { ...state }
                    delete newState[key]
                    return newState
                },
            },
        ],
    }),
    listeners(({ actions }) => ({
        acceptDataProcessing: ({ testOnlyOverride }) => {
            actions.updateOrganization({ is_ai_data_processing_approved: testOnlyOverride ?? true })
        },
    })),
    selectors({
        dataProcessingAccepted: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => !!currentOrganization?.is_ai_data_processing_approved,
        ],
        dataProcessingApprovalDisabledReason: [
            (s) => [s.currentOrganization],
            (currentOrganization): string | null =>
                !currentOrganization?.membership_level ||
                currentOrganization.membership_level < OrganizationMembershipLevel.Admin
                    ? `Ask an admin or owner of ${currentOrganization?.name} to approve this`
                    : null,
        ],
        tools: [(s) => [s.toolMap], (toolMap): ToolDefinition[] => Object.values(toolMap)],
    }),
])
