import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'

import { createEditor as createRichContentEditor } from 'lib/components/RichContentEditor/utils'
import { maxContextLogic } from 'scenes/max/maxContextLogic'
import type { ThreadMessage } from 'scenes/max/maxThreadLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { NotebookNodeType } from '../types'
import { textContent } from '../utils'
import {
    NotebookAI,
    NotebookAIPrompt,
    NotebookAIPromptExtension,
    NotebookAIPromptStatus,
    hasRetriableMaxFailure,
    submitNotebookAIPromptFromRange,
} from './NotebookAIPrompt'

describe('NotebookAIPromptExtension', () => {
    beforeEach(() => {
        initKeaTests()
        sidePanelStateLogic.mount()
    })

    afterEach(() => {
        maxContextLogic.unmount()
        sidePanelStateLogic.unmount()
    })

    function createEditor(): Editor {
        return new Editor({
            extensions: [
                StarterKit,
                NotebookAI,
                NotebookAIPrompt,
                NotebookAIPromptStatus,
                NotebookAIPromptExtension.configure({
                    shortId: 'abc123',
                    title: 'Revenue notebook',
                }),
            ],
            content: {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [
                            { type: NotebookNodeType.AIPrompt },
                            { type: 'text', text: ' how many users signed up yesterday?' },
                        ],
                    },
                ],
            },
        })
    }

    function createEditorWithText(text: string): Editor {
        return new Editor({
            extensions: [
                StarterKit,
                NotebookAI,
                NotebookAIPrompt,
                NotebookAIPromptStatus,
                NotebookAIPromptExtension.configure({
                    shortId: 'abc123',
                    title: 'Revenue notebook',
                }),
            ],
            content: {
                type: 'doc',
                content: [
                    {
                        type: 'paragraph',
                        content: [{ type: 'text', text }],
                    },
                ],
            },
        })
    }

    it('submits an inline AI prompt on Enter and leaves a pending AI placeholder', () => {
        const editor = createEditor()

        editor.commands.focus('end')
        editor.commands.keyboardShortcut('Enter')

        const aiNode = editor.getJSON().content?.[0]

        expect(aiNode).toEqual({
            type: NotebookNodeType.AI,
            attrs: { id: expect.any(String) },
        })
        expect(maxContextLogic.values.contextNotebooks[0].request_location?.current_block_text).toBe(
            `<AI id="${aiNode?.attrs?.id}">Thinking...</AI>`
        )
        expect(textContent(editor.state.doc)).toContain('<AI id="')
        expect(textContent(editor.state.doc)).toContain('>Thinking...</AI>')
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe('!how many users signed up yesterday?')

        editor.destroy()
    })

    it('replaces a typed /ai question range with a pending AI placeholder', () => {
        const text = '/ai add a haiku here'
        const editor = createEditorWithText(text)

        submitNotebookAIPromptFromRange(
            createRichContentEditor(editor),
            { from: 1, to: text.length + 1 },
            'add a haiku here',
            {
                shortId: 'abc123',
                title: 'Revenue notebook',
            }
        )

        const aiNode = editor.getJSON().content?.[0]

        expect(aiNode).toEqual({
            type: NotebookNodeType.AI,
            attrs: { id: expect.any(String) },
        })
        expect(maxContextLogic.values.contextNotebooks[0].request_location?.current_block_text).toBe(
            `<AI id="${aiNode?.attrs?.id}">Thinking...</AI>`
        )
        expect(textContent(editor.state.doc)).toContain('<AI id="')
        expect(textContent(editor.state.doc)).toContain('>Thinking...</AI>')
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe('!add a haiku here')

        editor.destroy()
    })

    it('treats failed Max responses as retriable placeholder failures', () => {
        const threadRaw = [
            {
                type: AssistantMessageType.Human,
                content: 'drop a sick dad joke here',
                status: 'completed',
                id: 'human-1',
            },
            {
                type: AssistantMessageType.Failure,
                content: 'You appear to be offline. Please check your internet connection.',
                status: 'completed',
                id: 'failure-1',
            },
        ] as ThreadMessage[]

        expect(hasRetriableMaxFailure(threadRaw)).toBe(true)
    })

    it('does not treat completed Max responses as retriable placeholder failures', () => {
        const threadRaw = [
            {
                type: AssistantMessageType.Human,
                content: 'drop a sick dad joke here',
                status: 'completed',
                id: 'human-1',
            },
            {
                type: AssistantMessageType.Assistant,
                content: 'A completed response',
                status: 'completed',
                id: 'assistant-1',
            },
        ] as ThreadMessage[]

        expect(hasRetriableMaxFailure(threadRaw)).toBe(false)
    })
})
