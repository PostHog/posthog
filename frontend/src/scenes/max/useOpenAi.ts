import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export interface UseOpenAiReturn {
    /** Whether the Max side panel is currently open */
    isMaxOpen: boolean
    /** Function to open AI - either as new tab (if flag enabled) or side panel */
    openAi: (initialPrompt?: string) => void
}

/**
 * Hook that abstracts opening PostHog AI.
 * When UX_REMOVE_SIDEPANEL_MAX flag is enabled, opens AI in a new tab.
 * Otherwise, opens the Max side panel.
 */
export function useOpenAi(): UseOpenAiReturn {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)
    const isRemovingSidePanelMax = useFeatureFlag('UX_REMOVE_SIDEPANEL_MAX')

    const isMaxOpen = sidePanelOpen && selectedTab === SidePanelTab.Max

    const openAi = (initialPrompt?: string): void => {
        if (isRemovingSidePanelMax) {
            newInternalTab(urls.ai(undefined, initialPrompt))
        } else {
            openSidePanel(SidePanelTab.Max, initialPrompt)
        }
    }

    return {
        isMaxOpen,
        openAi,
    }
}
