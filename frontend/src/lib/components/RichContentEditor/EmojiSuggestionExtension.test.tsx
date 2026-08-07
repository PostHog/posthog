import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Editor } from '@tiptap/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'

import { initKeaTests } from '~/test/init'

import { EmojiSuggestionPanel } from './EmojiSuggestionExtension'

// Render a stand-in for the frimousse picker: frimousse loads emoji data over the network and
// isn't meaningfully drivable in jsdom, so we assert the props we pass and fire a pick ourselves.
jest.mock('lib/components/EmojiPicker/EmojiPickerPanel', () => ({
    EmojiPickerPanel: ({ initialSearch, autoFocusSearch, onEmojiSelect }: any) => (
        <button
            data-attr="mock-emoji-panel"
            data-initial-search={initialSearch}
            data-autofocus={String(autoFocusSearch)}
            onClick={() => onEmojiSelect('🔥')}
        >
            pick
        </button>
    ),
}))

function createMockEditor(): { editor: Editor; run: jest.Mock; deleteRange: jest.Mock; insertContent: jest.Mock } {
    const run = jest.fn()
    const insertContent = jest.fn(() => ({ run }))
    const deleteRange = jest.fn(() => ({ insertContent }))
    const focus = jest.fn(() => ({ deleteRange }))
    const chain = jest.fn(() => ({ focus }))
    return { editor: { chain } as unknown as Editor, run, deleteRange, insertContent }
}

describe('EmojiSuggestionPanel', () => {
    beforeEach(() => {
        initKeaTests()
        emojiUsageLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('does not render the picker until a character follows the colon', () => {
        const { editor } = createMockEditor()
        render(
            <Provider>
                <EmojiSuggestionPanel
                    editor={editor}
                    range={{ from: 0, to: 1 }}
                    query=""
                    visible={false}
                    onClose={jest.fn()}
                />
            </Provider>
        )
        expect(screen.queryByTestId('mock-emoji-panel')).not.toBeInTheDocument()
    })

    it('seeds the picker search with the typed query and autofocuses it', () => {
        const { editor } = createMockEditor()
        render(
            <Provider>
                <EmojiSuggestionPanel
                    editor={editor}
                    range={{ from: 3, to: 6 }}
                    query="sm"
                    visible={true}
                    onClose={jest.fn()}
                />
            </Provider>
        )
        const panel = screen.getByTestId('mock-emoji-panel')
        expect(panel).toHaveAttribute('data-initial-search', 'sm')
        expect(panel).toHaveAttribute('data-autofocus', 'true')
    })

    it('replaces the :query range with the picked emoji, records usage and closes', async () => {
        const { editor, run, deleteRange, insertContent } = createMockEditor()
        const onClose = jest.fn()
        const range = { from: 3, to: 6 }

        render(
            <Provider>
                <EmojiSuggestionPanel editor={editor} range={range} query="sm" visible={true} onClose={onClose} />
            </Provider>
        )

        await expectLogic(emojiUsageLogic, () => {
            fireEvent.click(screen.getByTestId('mock-emoji-panel'))
        }).toDispatchActions(['emojiUsed'])

        expect(deleteRange).toHaveBeenCalledWith(range)
        expect(insertContent).toHaveBeenCalledWith('🔥')
        expect(run).toHaveBeenCalledTimes(1)
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('closes on Escape', () => {
        const { editor } = createMockEditor()
        const onClose = jest.fn()
        render(
            <Provider>
                <EmojiSuggestionPanel
                    editor={editor}
                    range={{ from: 0, to: 1 }}
                    query="s"
                    visible={true}
                    onClose={onClose}
                />
            </Provider>
        )
        fireEvent.keyDown(screen.getByTestId('mock-emoji-panel'), { key: 'Escape' })
        expect(onClose).toHaveBeenCalledTimes(1)
    })
})
