import { act, cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import * as retryImportModule from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { MAX_SIDE_PANEL_ID, SIDE_PANEL_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { aiShellLogic } from '~/layout/ai/aiShellLogic'
import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { todayPanelChatSessionLogic } from '~/layout/today/todayPanelChatSessionLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { UseMaxToolReturn, useMaxTool } from './useMaxTool'

function TestMaxTool({
    identifier = 'read_data',
    context,
    active = true,
    initialMaxPrompt,
    onRender,
}: {
    identifier?: 'read_data' | 'create_experiment'
    context: Record<string, unknown>
    active?: boolean
    initialMaxPrompt?: string
    onRender?: (result: UseMaxToolReturn) => void
}): null {
    const result = useMaxTool({
        identifier,
        context,
        active,
        initialMaxPrompt,
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
        const deregisterTool = jest.spyOn(aiShellLogic.actions, 'deregisterTool')
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

    // Scenes register their tools on the light shell store, before the Max logics load.
    it('keeps a tool registered before the Max logics mount', () => {
        logic.unmount()
        render(<TestMaxTool context={{ query: 'select 1' }} />)

        logic.mount()

        expect(logic.values.toolMap.read_data?.context).toEqual({ query: 'select 1' })
    })

    // The first open waits for the Max chunk. The click must still open the panel with the tool's prompt,
    // and the chat must get the page's context as it is when the chunk arrives, not as it was at the click.
    it.each([
        {
            change: 'the scene unmounts',
            whileLoading: (view: ReturnType<typeof render>): void => view.unmount(),
            expectedToolContext: [],
        },
        {
            change: 'the tool context changes',
            whileLoading: (view: ReturnType<typeof render>): void =>
                view.rerender(<TestMaxTool context={{ query: 'select 2' }} initialMaxPrompt="Why did signups drop?" />),
            expectedToolContext: [JSON.stringify({ query: 'select 2' })],
        },
    ])(
        'opens the panel with the prompt and current context when $change before the chunk arrives',
        async ({ whileLoading, expectedToolContext }) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true })
            const unmountContextStore = attachedContextLogic.mount()
            let openMax: UseMaxToolReturn['openMax'] = null
            const view = render(
                <TestMaxTool
                    context={{ query: 'select 1' }}
                    initialMaxPrompt="Why did signups drop?"
                    onRender={(result) => (openMax = result.openMax)}
                />
            )

            let opening: Promise<void> | undefined
            act(() => {
                opening = openMax?.()
            })
            whileLoading(view)
            await act(async () => {
                await opening
            })

            expect(sidePanelStateLogic.values).toMatchObject({
                selectedTab: SidePanelTab.Max,
                selectedTabOptions: 'Why did signups drop?',
            })
            expect(
                attachedContextLogic.values.contextItems
                    .filter((item) => item.type === 'tool_context')
                    .map((item) => item.value)
            ).toEqual(expectedToolContext)
            unmountContextStore()
        }
    )

    it('tells the person to reload when the Max chunk fails to load', async () => {
        jest.spyOn(retryImportModule, 'retryImport').mockRejectedValue(
            new Error('Failed to fetch dynamically imported module')
        )
        const showError = jest.spyOn(lemonToast, 'error')
        let openMax: UseMaxToolReturn['openMax'] = null
        render(<TestMaxTool context={{ query: 'select 1' }} onRender={(result) => (openMax = result.openMax)} />)

        await act(async () => {
            await expect(openMax?.()).resolves.toBeUndefined()
        })

        expect(showError).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ button: expect.objectContaining({ label: 'Reload' }) })
        )
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    it('opens the side panel on a new chat with the tool suggestions', async () => {
        let openMax: UseMaxToolReturn['openMax'] = null
        render(<TestMaxTool context={{ query: 'select 1' }} onRender={(result) => (openMax = result.openMax)} />)

        await act(async () => {
            await openMax?.()
        })

        expect(sidePanelStateLogic.values.selectedTab).toEqual(SidePanelTab.Max)
        expect(maxLogic({ panelId: SIDE_PANEL_PANEL_ID }).values.activeSuggestionGroup?.suggestions).toEqual([
            { content: 'Show me signups' },
        ])
    })

    it.each([
        { nav: 'Today', chat: 'task', todayRailNav: true, hintQueued: true, taskId: 'task-1' },
        { nav: 'Today', chat: 'draft', todayRailNav: true, hintQueued: true, taskId: undefined },
        { nav: 'classic', chat: 'task', todayRailNav: false, hintQueued: false, taskId: 'task-1' },
    ])('replaces an open $nav panel $chat chat with a new chat', async ({ todayRailNav, hintQueued, taskId }) => {
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
        await act(async () => {
            await openMax?.()
        })

        expect(runner.values.activeCreation).toBeNull()
        expect(panelChat.values.previousChatsHintQueued).toBe(hintQueued)
        expect(attachedContextLogic.values.contextItems).toEqual([
            expect.objectContaining({ type: 'page', key: expect.any(String) }),
            expect.objectContaining({ type: 'tool_context', value: JSON.stringify({ query: 'select 1' }) }),
        ])
        expect(sidePanelStateLogic.values.selectedTab).toEqual(SidePanelTab.Max)
        panelChat.unmount()
    })

    it('attaches only the last clicked tool context, keeps it current, and releases it once a task opens', async () => {
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
        await act(async () => {
            await openers.experiment?.()
        })
        await act(async () => {
            await openers.sql?.()
        })
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

        await act(async () => {
            await openers.sql?.()
        })
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
