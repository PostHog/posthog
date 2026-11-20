import { useValues } from 'kea'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { stashPendingMaxContext } from './maxLogic'
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
            stashPendingMaxContext(convertToMaxUIContext(context))
        }
        newInternalTab(urls.ai(undefined, initialPrompt))
    }

    return {
        isMaxOpen,
        openAi,
    }
}
