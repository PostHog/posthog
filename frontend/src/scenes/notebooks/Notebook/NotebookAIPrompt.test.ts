import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'

import { maxContextLogic } from 'scenes/max/maxContextLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { NotebookNodeType } from '../types'
import { NotebookAIPrompt, NotebookAIPromptExtension, NotebookAIPromptStatus } from './NotebookAIPrompt'

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

    it('submits an inline AI prompt on Enter and leaves a status placeholder', () => {
        const editor = createEditor()

        editor.commands.focus('end')
        editor.commands.keyboardShortcut('Enter')

        expect(editor.getJSON().content?.[0]).toEqual({
            type: 'paragraph',
            content: [
                {
                    type: NotebookNodeType.AIPromptStatus,
                    attrs: { prompt: 'how many users signed up yesterday?' },
                },
            ],
        })
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe('!how many users signed up yesterday?')

        editor.destroy()
    })
})
