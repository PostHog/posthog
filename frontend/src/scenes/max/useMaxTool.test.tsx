import { act, cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { MAX_SIDE_PANEL_ID, SIDE_PANEL_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { todayPanelChatSessionLogic } from '~/layout/today/todayPanelChatSessionLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { attachedContextLogic, runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { UseMaxToolReturn, useMaxTool } from './useMaxTool'

function TestMaxTool({
    identifier = 'read_data',
    context,
    active = true,
    onRender,
}: {
    identifier?: 'read_data' | 'create_experiment'
    context: Record<string, unknown>
    active?: boolean
    onRender?: (result: UseMaxToolReturn) => void
}): null {
    const result = useMaxTool({
        identifier,
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
        { nav: 'Today', chat: 'task', todayRailNav: true, hintQueued: true, taskId: 'task-1' },
        { nav: 'Today', chat: 'draft', todayRailNav: true, hintQueued: true, taskId: undefined },
        { nav: 'classic', chat: 'task', todayRailNav: false, hintQueued: false, taskId: 'task-1' },
    ])('replaces an open $nav panel $chat chat with a new chat', ({ todayRailNav, hintQueued, taskId }) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav,
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })
        const panelChat = todayPanelChatSessionLogic()
        panelChat.mount()
        const runner = runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID })
        runner.actions.setActiveCreation({ streamKey: 'run-1', taskId, runId: taskId && 'run-1' })

        let openMax: UseMaxToolReturn['openMax'] = null
        render(<TestMaxTool context={{ query: 'select 1' }} onRender={(result) => (openMax = result.openMax)} />)
        act(() => openMax?.())

        expect(runner.values.activeCreation).toBeNull()
        expect(panelChat.values.previousChatsHintQueued).toBe(hintQueued)
        expect(attachedContextLogic.values.contextItems).toEqual([
            expect.objectContaining({ type: 'page', key: expect.any(String) }),
            expect.objectContaining({ type: 'tool_context', value: JSON.stringify({ query: 'select 1' }) }),
        ])
        expect(sidePanelStateLogic.values.selectedTab).toEqual(SidePanelTab.Max)
        panelChat.unmount()
    })

    it('attaches only the last clicked tool context, keeps it current, and releases it once a task opens', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true })
        const unmountContextStore = attachedContextLogic.mount()
        const openers: Record<string, UseMaxToolReturn['openMax']> = {}
        const tools = (sqlQuery: string): JSX.Element => (
            <>
                <TestMaxTool context={{ query: sqlQuery }} onRender={(result) => (openers.sql = result.openMax)} />
                <TestMaxTool
                    identifier="create_experiment"
                    context={{ experiment: 'checkout' }}
                    onRender={(result) => (openers.experiment = result.openMax)}
                />
            </>
        )
        const toolContextValues = (): (string | undefined)[] =>
            attachedContextLogic.values.contextItems
                .filter((item) => item.type === 'tool_context')
                .map((item) => item.value)

        const { rerender, unmount } = render(tools('select 1'))
        act(() => openers.experiment?.())
        act(() => openers.sql?.())
        expect(toolContextValues()).toEqual([JSON.stringify({ query: 'select 1' })])

        rerender(tools('select 2'))
        expect(toolContextValues()).toEqual([JSON.stringify({ query: 'select 2' })])

        act(() => router.actions.push(urls.sqlEditor()))
        expect(attachedContextLogic.values.contextItems[0]).toMatchObject({ type: 'page', key: urls.sqlEditor() })

        const runner = runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID })
        act(() => runner.actions.setActiveCreation({ streamKey: 'draft-1' }))
        expect(attachedContextLogic.values.contextItems).toEqual([])

        act(() => runner.actions.clearActiveCreation())
        expect(toolContextValues()).toEqual([JSON.stringify({ query: 'select 2' })])

        act(() => runner.actions.setActiveCreation({ streamKey: 'draft-2', taskId: 'task-2', runId: 'run-2' }))
        act(() => runner.actions.clearActiveCreation())
        expect(attachedContextLogic.values.contextItems).toEqual([])

        act(() => openers.sql?.())
        rerender(
            <TestMaxTool
                context={{ query: 'select 2' }}
                active={false}
                onRender={(result) => (openers.sql = result.openMax)}
            />
        )
        expect(attachedContextLogic.values.contextItems).toEqual([])

        unmount()
        expect(attachedContextLogic.values.contextItems).toEqual([])
        unmountContextStore()
    })
})
