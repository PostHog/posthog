import { useActions, useValues } from 'kea'
import React, { useEffect, useMemo, useRef } from 'react'

import { IconWrench } from '@posthog/icons'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { ToolDefinition, ToolRegistration, getToolDefinition } from './max-constants'
import { maxGlobalLogic } from './maxGlobalLogic'
import { SIDE_PANEL_PANEL_ID, maxLogic } from './maxLogic'
import { createSuggestionGroup } from './utils'

export interface UseMaxToolOptions extends Omit<ToolRegistration, 'name' | 'description'> {
    /** Whether MaxTool functionality is active. When false, tool is not registered. */
    active?: boolean
    /** Initial prompt to pass to Max when opened */
    initialMaxPrompt?: string
    /** Callback when Max panel opens */
    onMaxOpen?: () => void
    /** Optional: Describes what kind of context information is being provided */
    contextDescription?: ToolRegistration['contextDescription']
}

export interface UseMaxToolReturn {
    /** Tool definition - null if the tool is inactive (i.e. `active` is false or Max is not available) */
    definition: ToolDefinition | null
    /** Whether the Max side panel is currently open */
    isMaxOpen: boolean
    /** Function to open Max with the optional initialMaxPrompt and suggestions - null if the tool is inactive */
    openMax: (() => void) | null
}

/** Hook for registering a MaxTool and handling Max interactions programmatically, without the full MaxTool wrapper. */
export function useMaxTool({
    identifier,
    context,
    contextDescription,
    introOverride,
    callback,
    clientExecution,
    suggestions,
    active = true,
    initialMaxPrompt,
    onMaxOpen,
}: UseMaxToolOptions): UseMaxToolReturn {
    const { registerTool, deregisterTool } = useActions(maxGlobalLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { setActiveGroup, startNewConversation } = useActions(maxLogic({ panelId: SIDE_PANEL_PANEL_ID }))

    const definition = getToolDefinition(identifier)
    const isMaxOpen = sidePanelOpen && selectedTab === SidePanelTab.Max
    const activeIdentifierRef = useRef<string | null>(null)
    const contextKey = useMemo(() => JSON.stringify(context), [context])

    useEffect(() => {
        if (!active || !definition) {
            if (activeIdentifierRef.current) {
                deregisterTool(activeIdentifierRef.current)
                activeIdentifierRef.current = null
            }
            return
        }

        if (activeIdentifierRef.current && activeIdentifierRef.current !== identifier) {
            deregisterTool(activeIdentifierRef.current)
        }

        activeIdentifierRef.current = identifier
        registerTool({
            identifier,
            name: definition.name,
            description: definition.description,
            context,
            contextDescription,
            introOverride,
            suggestions,
            callback,
            clientExecution,
        })
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- context is tracked via contextKey (serialized) so identity churn doesn't re-register the tool
    }, [
        active,
        identifier,
        definition,
        contextKey,
        contextDescription,
        introOverride,
        suggestions,
        callback,
        clientExecution,
        registerTool,
        deregisterTool,
    ])

    useEffect(() => {
        return (): void => {
            if (activeIdentifierRef.current) {
                deregisterTool(activeIdentifierRef.current)
                activeIdentifierRef.current = null
            }
        }
    }, [deregisterTool])

    return {
        definition: active ? definition : null,
        isMaxOpen,
        openMax: !active
            ? null
            : (): void => {
                  // Start a new conversation so the prompt doesn't get added to an existing session
                  startNewConversation()
                  // Show the suggestions from this specific tool
                  if (definition && suggestions && suggestions.length > 0) {
                      setActiveGroup(
                          createSuggestionGroup(definition.name, React.createElement(IconWrench), suggestions)
                      )
                  }
                  openSidePanel(SidePanelTab.Max, initialMaxPrompt)
                  onMaxOpen?.()
              },
    }
}
