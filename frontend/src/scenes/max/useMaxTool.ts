import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useEffect, useMemo, useRef } from 'react'

import { IconWrench } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { sceneLogic } from 'scenes/sceneLogic'
import { sceneConfigurations } from 'scenes/scenes'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { todayAiChatLogic } from '~/layout/today/todayAiChatLogic'
import { SidePanelTab } from '~/types'

import { attachedContextItemKey, attachedContextLogic, runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'
import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { ToolDefinition, ToolRegistration, getToolDefinition } from './max-constants'
import { maxGlobalLogic } from './maxGlobalLogic'
import { sidePanelMaxLogic } from './maxLogic'
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

const MAX_TOOL_CONTEXT_LENGTH = 4096
const TOOL_PAGE_CONTEXT_PROVIDER_ID = 'max-tool-page'
let toolPageContextOwner: string | null = null

function toolPageContextItems(
    identifier: string,
    context: Record<string, unknown> | undefined,
    dismissGroup: string
): AttachedContextItem[] {
    const path = removeProjectIdIfPresent(router.values.location.pathname)
    const sceneId = sceneLogic.findMounted()?.values.activeSceneId
    const sceneName = sceneId ? sceneConfigurations[sceneId]?.name : undefined
    const items: AttachedContextItem[] = [{ type: 'page', key: path, label: sceneName || path, dismissGroup }]
    const value = context && Object.keys(context).length > 0 ? JSON.stringify(context) : null
    if (value && value.length <= MAX_TOOL_CONTEXT_LENGTH) {
        items.push({ type: 'tool_context', label: identifier, value, hidden: true, dismissGroup })
    }
    return items
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
    const { registerContext, deregisterContext, undismissContext } = useActions(attachedContextLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        location: { pathname },
    } = useValues(router)
    const { activeCreation } = useValues(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }))
    const openChat = activeCreation ? (activeCreation.taskId ? 'task' : 'draft') : null

    const definition = getToolDefinition(identifier)
    const isMaxOpen = sidePanelOpen && selectedTab === SidePanelTab.Max
    const activeIdentifierRef = useRef<string | null>(null)
    const hookIdRef = useRef<string>(uuid())
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
        if (toolPageContextOwner !== hookIdRef.current) {
            return
        }
        if (!active || openChat === 'task') {
            toolPageContextOwner = null
            deregisterContext(TOOL_PAGE_CONTEXT_PROVIDER_ID)
            return
        }
        if (openChat === 'draft') {
            deregisterContext(TOOL_PAGE_CONTEXT_PROVIDER_ID)
            return
        }
        registerContext(
            TOOL_PAGE_CONTEXT_PROVIDER_ID,
            toolPageContextItems(identifier, context, TOOL_PAGE_CONTEXT_PROVIDER_ID)
        )
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- context is tracked via contextKey (serialized)
    }, [active, identifier, contextKey, pathname, openChat, registerContext, deregisterContext])

    useEffect(() => {
        const hookId = hookIdRef.current
        return (): void => {
            if (activeIdentifierRef.current) {
                deregisterTool(activeIdentifierRef.current)
                activeIdentifierRef.current = null
            }
            if (toolPageContextOwner === hookId) {
                toolPageContextOwner = null
                deregisterContext(TOOL_PAGE_CONTEXT_PROVIDER_ID)
            }
        }
    }, [deregisterTool, deregisterContext])

    return {
        definition: active ? definition : null,
        isMaxOpen,
        openMax: !active
            ? null
            : (): void => {
                  const { startNewConversation, setActiveGroup } = sidePanelMaxLogic().actions
                  // Start a new conversation so the prompt doesn't get added to an existing session
                  if (featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]) {
                      // The Today panel can show a task chat too, so its own logic starts the new chat.
                      const unmount = todayAiChatLogic.mount()
                      todayAiChatLogic.actions.startNewChatForTool()
                      unmount()
                  } else if (maxGlobalLogic.values.effectivePhaiView === 'new') {
                      const runner = runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID })
                      const unmount = runner.mount()
                      runner.actions.clearActiveCreation()
                      runner.actions.setHistoryExpanded(false)
                      unmount()
                  } else {
                      startNewConversation()
                  }
                  if (maxGlobalLogic.values.effectivePhaiView === 'new') {
                      toolPageContextOwner = hookIdRef.current
                      const items = toolPageContextItems(identifier, context, TOOL_PAGE_CONTEXT_PROVIDER_ID)
                      undismissContext(attachedContextItemKey(items[0]), TOOL_PAGE_CONTEXT_PROVIDER_ID)
                      registerContext(TOOL_PAGE_CONTEXT_PROVIDER_ID, items)
                  }
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
