import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { retryImport } from 'lib/utils/retryImport'
import { sceneLogic } from 'scenes/sceneLogic'
import { sceneConfigurations } from 'scenes/scenes'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { aiShellLogic } from '~/layout/ai/aiShellLogic'
import { attachedContextItemKey } from '~/layout/ai/attachedContext'
import type { AttachedContextItem } from '~/layout/ai/attachedContext'
import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { ToolDefinition, ToolRegistration, getToolDefinition } from './max-constants'

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
    /** Function to open Max with the optional initialMaxPrompt and suggestions - null if the tool is inactive.
     * It resolves once the panel is open: the first call waits for the Max chunk. */
    openMax: (() => Promise<void>) | null
}

// The chat logics stay out of the shell chunk. The shell loads them on the first open.
const loadMaxToolOpener = (): Promise<typeof import('./maxToolOpener')> => retryImport(() => import('./maxToolOpener'))

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
    const { registerTool, deregisterTool } = useActions(aiShellLogic)
    const { effectivePhaiView } = useValues(aiShellLogic)
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
    const unmountedRef = useRef(false)
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
        unmountedRef.current = false
        return (): void => {
            unmountedRef.current = true
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
            : async (): Promise<void> => {
                  const { startToolChat, showToolSuggestions } = await loadMaxToolOpener()
                  startToolChat({ todayRailNav: !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV], effectivePhaiView })
                  // The page may have changed while the chunk loaded. Its context would then outlive the hook.
                  if (effectivePhaiView === 'new' && !unmountedRef.current) {
                      toolPageContextOwner = hookIdRef.current
                      const items = toolPageContextItems(identifier, context, TOOL_PAGE_CONTEXT_PROVIDER_ID)
                      undismissContext(attachedContextItemKey(items[0]), TOOL_PAGE_CONTEXT_PROVIDER_ID)
                      registerContext(TOOL_PAGE_CONTEXT_PROVIDER_ID, items)
                  }
                  // Show the suggestions from this specific tool
                  if (definition && suggestions && suggestions.length > 0) {
                      showToolSuggestions(definition.name, suggestions)
                  }
                  openSidePanel(SidePanelTab.Max, initialMaxPrompt)
                  onMaxOpen?.()
              },
    }
}
