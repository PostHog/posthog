import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'

import { IconWrench } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { createSuggestionGroup } from './utils'

export interface UseMaxToolOptions extends Omit<ToolRegistration, 'name' | 'description'> {
    /** Whether MaxTool functionality is active. When false, tool is not registered. */
    active?: boolean
    /** Initial prompt to pass to Max when opened */
    initialMaxPrompt?: string
    /** Callback when Max panel opens */
    onMaxOpen?: () => void
}

export interface UseMaxToolReturn {
    /** Tool definition - null if the tool is inactive (i.e. `active` is false or Max is not available) */
    definition: (typeof TOOL_DEFINITIONS)[keyof typeof TOOL_DEFINITIONS] | null
    /** Whether the Max side panel is currently open */
    isMaxOpen: boolean
    /** Function to open Max with the optional initialMaxPrompt and suggestions - null if the tool is inactive */
    openMax: (() => void) | null
}

/** Hook for registering a MaxTool and handling Max interactions programmatically, without the full MaxTool wrapper. */
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
    const { setActiveGroup } = useActions(maxLogic)

    const definition = TOOL_DEFINITIONS[identifier as keyof typeof TOOL_DEFINITIONS]
    const isMaxAvailable = useFeatureFlag('ARTIFICIAL_HOG')
    const isMaxOpen = isMaxAvailable && sidePanelOpen && selectedTab === SidePanelTab.Max

    if (!isMaxAvailable) {
        active = false
    }

    useEffect(() => {
        // Register/deregister tool
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
            return (): void => deregisterTool(identifier)
        }
    }, [
        active,
        identifier,
        definition.name,
        definition.description,
        icon,
        JSON.stringify(context), // oxlint-disable-line react-hooks/exhaustive-deps
        introOverride,
        suggestions,
        callback,
        registerTool,
        deregisterTool,
    ])

    return {
        definition: active ? definition : null,
        isMaxOpen,
        openMax: !active
            ? null
            : (): void => {
                  // Show the suggestions from this specific tool
                  if (suggestions && suggestions.length > 0) {
                      setActiveGroup(
                          createSuggestionGroup(definition.name, React.createElement(IconWrench), suggestions)
                      )
                  }
                  openSidePanel(SidePanelTab.Max, initialMaxPrompt)
                  onMaxOpen?.()
              },
    }
}
