import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { createRef, type RefObject } from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxContextLogic } from 'scenes/max/maxContextLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { NotebookNodeType, type NotebookEditor } from '../types'
import { notebookLogic, type NotebookLogicProps } from './notebookLogic'
import { SlashCommands } from './SlashCommands'

const NOTEBOOK_PROPS: NotebookLogicProps = {
    shortId: 'abc123',
    mode: 'notebook',
}

type SlashCommandsHandle = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

function rangeForQuery(query: string): { from: number; to: number } {
    const from = 3
    return { from, to: from + 1 + query.length }
}

function createEditor(): {
    editor: NotebookEditor
    promptChain: {
        insertContentAt: jest.Mock
        setTextSelection: jest.Mock
        run: jest.Mock
    }
    deleteChain: {
        run: jest.Mock
    }
} {
    const promptChain = {
        insertContentAt: jest.fn(),
        setTextSelection: jest.fn(),
        run: jest.fn(() => true),
    }
    promptChain.insertContentAt.mockReturnValue(promptChain)
    promptChain.setTextSelection.mockReturnValue(promptChain)

    const deleteChain = {
        run: jest.fn(() => true),
    }
    const editor = {
        getSelectedNode: jest.fn(() => null),
        chain: jest.fn(() => promptChain),
        deleteRange: jest.fn(() => deleteChain),
        getAdjacentNodes: jest.fn(() => ({ previous: null, next: null })),
    } as unknown as NotebookEditor

    return { editor, promptChain, deleteChain }
}

describe('SlashCommands', () => {
    let logic: ReturnType<typeof notebookLogic.build> | null = null

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/notebooks/:short_id/kernel/status/': () => [200, null],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        sidePanelStateLogic.mount()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        logic = null
        maxContextLogic.unmount()
        sidePanelStateLogic.unmount()
        featureFlagLogic.unmount()
    })

    function renderSlashCommands(
        query: string,
        editor: NotebookEditor,
        onClose: () => void = jest.fn(),
        ref?: RefObject<SlashCommandsHandle>
    ): void {
        logic = notebookLogic(NOTEBOOK_PROPS)
        logic.mount()
        logic.actions.setEditor(editor)

        render(
            <BindLogic logic={notebookLogic} props={NOTEBOOK_PROPS}>
                <SlashCommands ref={ref} mode="slash" range={rangeForQuery(query)} query={query} onClose={onClose} />
            </BindLogic>
        )
    }

    it('turns an empty /ai command into an editable prompt line', () => {
        const { editor, promptChain, deleteChain } = createEditor()
        const onClose = jest.fn()

        renderSlashCommands('ai', editor, onClose)
        fireEvent.click(screen.getByRole('button', { name: 'AI' }))

        expect(editor.deleteRange).not.toHaveBeenCalled()
        expect(deleteChain.run).not.toHaveBeenCalled()
        expect(promptChain.insertContentAt).toHaveBeenCalledWith(rangeForQuery('ai'), [
            { type: NotebookNodeType.AIPrompt },
            { type: 'text', text: ' ' },
        ])
        expect(promptChain.setTextSelection).toHaveBeenCalledWith(rangeForQuery('ai').from + 2)
        expect(promptChain.run).toHaveBeenCalled()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(onClose).toHaveBeenCalled()
    })

    it.each([
        { key: 'Tab', label: 'tab' },
        { key: 'Enter', label: 'enter' },
        { key: ' ', label: 'space' },
    ])('turns an empty /ai command into an editable prompt line on $label', ({ key }) => {
        const { editor, promptChain } = createEditor()
        const menuRef = createRef<SlashCommandsHandle>()

        renderSlashCommands('ai', editor, jest.fn(), menuRef)

        let handled = false
        act(() => {
            handled = menuRef.current?.onKeyDown({ key } as KeyboardEvent) ?? false
        })

        expect(handled).toBe(true)
        expect(promptChain.insertContentAt).toHaveBeenCalledWith(rangeForQuery('ai'), [
            { type: NotebookNodeType.AIPrompt },
            { type: 'text', text: ' ' },
        ])
    })

    it('opens Max and leaves a status placeholder after a question is typed in the /ai prompt', () => {
        const { editor, promptChain, deleteChain } = createEditor()
        const onClose = jest.fn()
        const query = 'ai how many users signed up yesterday?'
        const range = rangeForQuery(query)

        renderSlashCommands(query, editor, onClose)
        fireEvent.click(screen.getByRole('button', { name: 'AI' }))

        expect(editor.deleteRange).not.toHaveBeenCalled()
        expect(deleteChain.run).not.toHaveBeenCalled()
        expect(promptChain.insertContentAt).toHaveBeenCalledWith(range, [
            {
                type: NotebookNodeType.AIPromptStatus,
                attrs: { prompt: 'how many users signed up yesterday?' },
            },
        ])
        expect(promptChain.run).toHaveBeenCalled()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe('!how many users signed up yesterday?')
        expect(onClose).toHaveBeenCalled()
    })
})
