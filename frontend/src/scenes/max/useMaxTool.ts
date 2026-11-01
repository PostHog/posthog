import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useRef, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { retryImport } from 'lib/utils/retryImport'
import { reloadAfterChunkLoadError } from 'lib/utils/stableChunks'
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

import type { ToolDefinition, ToolRegistration } from './max-constants'

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
    /** Tool definition - null if the tool is inactive (i.e. `active` is false or Max is not available), or while the tool table loads */
    definition: ToolDefinition | null
    /** Whether the Max side panel is currently open */
    isMaxOpen: boolean
    /** Function to open Max with the optional initialMaxPrompt and suggestions - null if the tool is inactive.
     * It resolves once the panel is open: the first call waits for the Max chunk. */
    openMax: (() => Promise<void>) | null
}

// The chat logics stay out of the shell chunk. The shell loads them on the first open.
const loadMaxToolOpener = (): Promise<typeof import('./maxToolOpener')> => retryImport(() => import('./maxToolOpener'))

// The tool table holds the copy, icons and formatters of every tool. It stays out of the shell chunk,
// and loads once a page turns a tool on.
type ToolDefinitionsModule = typeof import('./max-constants')
let loadedToolDefinitions: ToolDefinitionsModule | null = null
async function loadToolDefinitions(): Promise<ToolDefinitionsModule> {
    loadedToolDefinitions ??= await retryImport(() => import('./max-constants'))
    return loadedToolDefinitions
}

function useToolDefinitions(active: boolean): ToolDefinitionsModule | null {
    const [toolDefinitions, setToolDefinitions] = useState(loadedToolDefinitions)
    useEffect(() => {
        if (!active || toolDefinitions) {
            return
        }
        let cancelled = false
        loadToolDefinitions().then(
            (module) => {
                if (!cancelled) {
                    setToolDefinitions(module)
                }
            },
            // A failed load leaves only the tool name and tooltip missing. A click on openMax tells the person to reload.
            () => {}
        )
        return (): void => {
            cancelled = true
        }
    }, [active, toolDefinitions])
    return toolDefinitions
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

    const definition = useToolDefinitions(active)?.getToolDefinition(identifier) ?? null
    const isMaxOpen = sidePanelOpen && selectedTab === SidePanelTab.Max
    const activeIdentifierRef = useRef<string | null>(null)
    const hookIdRef = useRef<string>(uuid())
    const unmountedRef = useRef(false)
    // openMax reads these after the chunk loads, so a change made meanwhile decides what reaches the chat.
    const latestRef = useRef({ context, active })
    latestRef.current = { context, active }
    const contextKey = useMemo(() => JSON.stringify(context), [context])

    // The tool registers before the tool table loads, so a message sent at once still carries its context.
    // The name and description arrive with the table.
    useEffect(() => {
        if (!active) {
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
            name: definition?.name,
            description: definition?.description,
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
                  let opener: Awaited<ReturnType<typeof loadMaxToolOpener>>
                  let toolDefinitions: ToolDefinitionsModule
                  try {
                      ;[opener, toolDefinitions] = await Promise.all([loadMaxToolOpener(), loadToolDefinitions()])
                  } catch (error) {
                      // Click handlers drop a rejected promise, and no error boundary sees it.
                      lemonToast.error("Couldn't open PostHog AI. Reload the page to try again.", {
                          button: { label: 'Reload', action: () => reloadAfterChunkLoadError(error) },
                      })
                      return
                  }
                  const { startToolChat, showToolSuggestions } = opener
                  startToolChat({ todayRailNav: !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV], effectivePhaiView })
                  // The page may have closed, or the tool turned off, while the chunk loaded. Its context would then outlive the hook.
                  if (effectivePhaiView === 'new' && !unmountedRef.current && latestRef.current.active) {
                      toolPageContextOwner = hookIdRef.current
                      const items = toolPageContextItems(
                          identifier,
                          latestRef.current.context,
                          TOOL_PAGE_CONTEXT_PROVIDER_ID
                      )
                      undismissContext(attachedContextItemKey(items[0]), TOOL_PAGE_CONTEXT_PROVIDER_ID)
                      registerContext(TOOL_PAGE_CONTEXT_PROVIDER_ID, items)
                  }
                  // Show the suggestions from this specific tool
                  const toolDefinition = toolDefinitions.getToolDefinition(identifier)
                  if (toolDefinition && suggestions && suggestions.length > 0) {
                      showToolSuggestions(toolDefinition.name, suggestions)
                  }
                  openSidePanel(SidePanelTab.Max, initialMaxPrompt)
                  onMaxOpen?.()
              },
    }
}
