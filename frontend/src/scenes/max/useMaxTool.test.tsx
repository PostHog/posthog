import { act, cleanup, render } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { todayPanelChatSessionLogic } from '~/layout/today/todayPanelChatSessionLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'

import { MAX_SIDE_PANEL_ID } from './components/PhaiSidePanelChat'
import { maxGlobalLogic } from './maxGlobalLogic'
import { SIDE_PANEL_PANEL_ID, maxLogic } from './maxLogic'
import { UseMaxToolReturn, useMaxTool } from './useMaxTool'

function TestMaxTool({
    context,
    active = true,
    onRender,
}: {
    context: Record<string, unknown>
    active?: boolean
    onRender?: (result: UseMaxToolReturn) => void
}): null {
    const result = useMaxTool({
        identifier: 'read_data',
        context,
        active,
        suggestions: ['Show me signups'],
    })
    onRender?.(result)

    return null
}

describe('useMaxTool', () => {
    let logic: ReturnType<typeof maxGlobalLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = maxGlobalLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('updates the registered tool context without deregistering between updates', () => {
        const deregisterTool = jest.spyOn(logic.actions, 'deregisterTool')
        const { rerender, unmount } = render(<TestMaxTool context={{ query: 'select 1' }} />)

        expect(logic.values.registeredToolMap.read_data?.context).toEqual({ query: 'select 1' })

        rerender(<TestMaxTool context={{ query: 'select 2' }} />)

        expect(logic.values.registeredToolMap.read_data?.context).toEqual({ query: 'select 2' })
        expect(deregisterTool).not.toHaveBeenCalled()

        unmount()

        expect(deregisterTool).toHaveBeenCalledWith('read_data')
    })

    it('does not reload the chat history when a scene registers a tool', async () => {
        await expectLogic(logic).toDispatchActions(['loadConversationHistorySuccess'])
        const listConversations = jest.spyOn(api.conversations, 'list')

        render(<TestMaxTool context={{ query: 'select 1' }} />)
        await expectLogic(logic).toFinishAllListeners()

        expect(listConversations).not.toHaveBeenCalled()
    })

    it('opens the side panel on a new chat with the tool suggestions', () => {
        let openMax: UseMaxToolReturn['openMax'] = null
        render(<TestMaxTool context={{ query: 'select 1' }} onRender={(result) => (openMax = result.openMax)} />)

        act(() => openMax?.())

        expect(sidePanelStateLogic.values.selectedTab).toEqual(SidePanelTab.Max)
        expect(maxLogic({ panelId: SIDE_PANEL_PANEL_ID }).values.activeSuggestionGroup?.suggestions).toEqual([
            { content: 'Show me signups' },
        ])
    })

    it.each([
        { nav: 'Today', todayRailNav: true, hintQueued: true },
        { nav: 'classic', todayRailNav: false, hintQueued: false },
    ])('replaces an open $nav panel task chat with a new chat', ({ todayRailNav, hintQueued }) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav,
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })
        const panelChat = todayPanelChatSessionLogic()
        panelChat.mount()
        const runner = runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID })
        runner.actions.setActiveCreation({ streamKey: 'run-1', taskId: 'task-1', runId: 'run-1' })

        let openMax: UseMaxToolReturn['openMax'] = null
        render(<TestMaxTool context={{ query: 'select 1' }} onRender={(result) => (openMax = result.openMax)} />)
        act(() => openMax?.())

        expect(runner.values.activeCreation).toBeNull()
        expect(panelChat.values.previousChatsHintQueued).toBe(hintQueued)
        expect(sidePanelStateLogic.values.selectedTab).toEqual(SidePanelTab.Max)
        panelChat.unmount()
    })
})
