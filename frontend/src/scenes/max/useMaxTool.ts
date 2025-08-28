import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import { maxGlobalLogic } from './maxGlobalLogic'

export interface UseMaxToolOptions extends Omit<ToolRegistration, 'name' | 'description'> {
    /** Whether MaxTool functionality is active. When false, tool is not registered. */
    active?: boolean
    /** Initial prompt to pass to Max when opened */
    initialMaxPrompt?: string
    /** Callback when Max panel opens */
    onMaxOpen?: () => void
}

export interface UseMaxToolReturn {
    /** Whether Max feature is available and tool is active */
    isMaxAvailable: boolean
    /** Whether Max panel is currently open */
    isMaxOpen: boolean
    /** Function to open Max with optional prompt and suggestions */
    openMax: () => void
    /** Tool definition from constants */
    definition: (typeof TOOL_DEFINITIONS)[keyof typeof TOOL_DEFINITIONS]
}

/**
 * Hook for registering a MaxTool and handling Max interactions without UI components.
 * This allows components to register tools programmatically without needing the full MaxTool wrapper.
 * 
 * Use this hook when you want to:
 * - Register a Max tool from components that can't wrap content with MaxTool
 * - Add Max functionality to dropdown menus or other non-wrappable UI elements
 * - Programmatically control Max tool registration based on complex conditions
 * 
 * The hook handles tool registration/deregistration automatically and provides
 * utilities to open Max with the appropriate context.
 * 
 * @example
 * ```tsx
 * function MyComponent() {
 *   const { isMaxAvailable, openMax } = useMaxTool({
 *     identifier: 'my_tool',
 *     context: { someData: 'value' },
 *     suggestions: ['Ask Max to help with this feature'],
 *   })
 * 
 *   return (
 *     <button onClick={openMax} disabled={!isMaxAvailable}>
 *       Get Max Help
 *     </button>
 *   )
 * }
 * ```
 */
export function useMaxTool({
    identifier,
    icon,
    context,
    introOverride,
    callback,
    suggestions,
    active = true,
    initialMaxPrompt,
    onMaxOpen,
}: UseMaxToolOptions): UseMaxToolReturn {
    const { registerTool, deregisterTool } = useActions(maxGlobalLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)

    const definition = TOOL_DEFINITIONS[identifier as keyof typeof TOOL_DEFINITIONS]
    const isMaxAvailable = useFeatureFlag('ARTIFICIAL_HOG') && active
    const isMaxOpen = isMaxAvailable && sidePanelOpen && selectedTab === SidePanelTab.Max

    // Register/deregister tool effect
    useEffect(() => {
        if (active) {
            registerTool({
                identifier,
                name: definition.name,
                description: definition.description,
                icon,
                context,
                introOverride,
                suggestions,
                callback,
            })
            return (): void => {
                deregisterTool(identifier)
            }
        }
    }, [
        active,
        identifier,
        definition.name,
        definition.description,
        icon,
        JSON.stringify(context),
        introOverride,
        JSON.stringify(suggestions),
        callback,
        registerTool,
        deregisterTool,
    ]) // oxlint-disable-line react-hooks/exhaustive-deps

    const openMax = (): void => {
        if (!isMaxAvailable) return

        // Include both initial prompt and suggestions
        let options = initialMaxPrompt
        if (suggestions && suggestions.length > 0) {
            options = JSON.stringify({
                prompt: initialMaxPrompt,
                suggestions: suggestions,
            })
        }
        openSidePanel(SidePanelTab.Max, options)
        onMaxOpen?.()
    }

    return {
        isMaxAvailable,
        isMaxOpen,
        openMax,
        definition,
    }
}