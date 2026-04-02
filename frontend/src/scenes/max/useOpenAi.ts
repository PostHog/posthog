import { useValues } from 'kea'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { PENDING_MAX_CONTEXT_KEY } from './maxLogic'
import { MaxOpenContext, convertToMaxUIContext } from './utils'

export interface UseOpenAiReturn {
    /** Whether the Max side panel is currently open */
    isMaxOpen: boolean
    /** Function to open AI in a new tab */
    openAi: (initialPrompt?: string, context?: MaxOpenContext) => void
}

export function useOpenAi(): UseOpenAiReturn {
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)

    const isMaxOpen = sidePanelOpen && selectedTab === SidePanelTab.Max

    const openAi = (initialPrompt?: string, context?: MaxOpenContext): void => {
        if (context) {
            try {
                const storedContext = {
                    context: convertToMaxUIContext(context),
                    timestamp: Date.now(),
                }
                sessionStorage.setItem(PENDING_MAX_CONTEXT_KEY, JSON.stringify(storedContext))
            } catch {
                // sessionStorage unavailable, silently fail, agent will handle it
            }
        }
        newInternalTab(urls.ai(undefined, initialPrompt))
    }

    return {
        isMaxOpen,
        openAi,
    }
}
