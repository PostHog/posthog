import React from 'react'

import { IconWrench } from '@posthog/icons'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import type { PhaiViewMode } from '~/layout/ai/aiPanelIds'
import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { todayAiChatLogic } from '~/layout/today/todayAiChatLogic'

import { sidePanelMaxLogic } from './maxLogic'
import { createSuggestionGroup } from './utils'

/** Starts a new side panel chat, so the tool's prompt does not land in an existing session. */
export function startToolChat({
    todayRailNav,
    effectivePhaiView,
}: {
    todayRailNav: boolean
    effectivePhaiView: PhaiViewMode
}): void {
    if (todayRailNav) {
        // The Today panel can show a task chat too, so its own logic starts the new chat.
        const unmount = todayAiChatLogic.mount()
        todayAiChatLogic.actions.startNewChatForTool()
        unmount()
    } else if (effectivePhaiView === 'new') {
        const runner = runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID })
        const unmount = runner.mount()
        runner.actions.clearActiveCreation()
        runner.actions.setHistoryExpanded(false)
        unmount()
    } else {
        sidePanelMaxLogic().actions.startNewConversation()
    }
}

export function showToolSuggestions(toolName: string, suggestions: string[]): void {
    sidePanelMaxLogic().actions.setActiveGroup(
        createSuggestionGroup(toolName, React.createElement(IconWrench), suggestions)
    )
}
