import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'
import { BindLogic } from 'kea'

import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { initKeaTests } from '~/test/init'

import { isCurrentNodeEmpty } from '../utils'
import { FloatingSuggestions } from './FloatingSuggestions'

jest.mock('lib/hooks/useResizeObserver', () => ({
    useResizeObserver: jest.fn(),
}))

jest.mock('../utils', () => ({
    isCurrentNodeEmpty: jest.fn(),
}))

// The fallback suggestion renders a popover we don't care about here — stub its view.
jest.mock('./SlashCommands', () => ({
    __esModule: true,
    default: { Component: () => null },
}))

describe('FloatingSuggestions', () => {
    const setRef = jest.fn()
    let mountHandler: (() => void) | undefined
    let updateHandler: (() => void) | undefined
    let editorView: { dom: HTMLElement } | null
    const flags = { hasFocus: false, isEditable: false, isActiveParagraph: false }

    // In tiptap v3 `editor.view` is a throwing proxy until the ProseMirror view mounts, so the
    // component reads `editorView` (via getTiptapEditorDom) and binds the observer on the 'mount' event.
    const fakeEditor = {
        on: jest.fn((event: string, cb: () => void) => {
            if (event === 'mount') {
                mountHandler = cb
            }
            if (event === 'update' || event === 'selectionUpdate') {
                updateHandler = cb
            }
        }),
        off: jest.fn(),
        isDestroyed: false,
        isActive: (name: string) => name === 'paragraph' && flags.isActiveParagraph,
        get isEditable() {
            return flags.isEditable
        },
        view: { hasFocus: () => flags.hasFocus },
        get editorView() {
            return editorView
        },
    }

    const renderComponent = (): ReturnType<typeof render> =>
        render(
            <BindLogic logic={richContentEditorLogic} props={{ logicKey: 'test', editor: fakeEditor as any }}>
                <FloatingSuggestions />
            </BindLogic>
        )

    const isSuggestionVisible = (container: HTMLElement): boolean =>
        container.querySelector('.FloatingSuggestion') !== null

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mountHandler = undefined
        updateHandler = undefined
        editorView = null
        flags.hasFocus = false
        flags.isEditable = false
        flags.isActiveParagraph = false
        jest.mocked(useResizeObserver).mockReturnValue({ ref: setRef, height: 0 } as any)
        jest.mocked(isCurrentNodeEmpty).mockReturnValue(false)
    })

    afterEach(() => {
        cleanup()
    })

    describe('resize observer lifecycle', () => {
        it('does not throw or attach the observer when the view is not mounted yet', () => {
            expect(() => renderComponent()).not.toThrow()
            expect(setRef).not.toHaveBeenCalled()
        })

        it('attaches the observer to the editor dom when the view is already mounted', () => {
            const dom = document.createElement('div')
            editorView = { dom }

            renderComponent()

            expect(setRef).toHaveBeenCalledWith(dom)
        })

        it('attaches the observer once the view (re)mounts — AI notebooks rebuild the editor', () => {
            renderComponent()
            expect(setRef).not.toHaveBeenCalled()

            const dom = document.createElement('div')
            editorView = { dom }
            mountHandler?.()

            expect(setRef).toHaveBeenCalledWith(dom)
        })
    })

    describe('suggestion visibility', () => {
        const allConditionsMet = { hasFocus: true, isEditable: true, isActiveParagraph: true, nodeEmpty: true }

        it.each([
            ['all conditions met', allConditionsMet, true],
            ['editor is not focused', { ...allConditionsMet, hasFocus: false }, false],
            ['editor is not editable', { ...allConditionsMet, isEditable: false }, false],
            ['cursor is not in a paragraph', { ...allConditionsMet, isActiveParagraph: false }, false],
            ['current node is not empty', { ...allConditionsMet, nodeEmpty: false }, false],
        ])('shows the suggestion only when %s', (_label, conditions, expected) => {
            editorView = { dom: document.createElement('div') }
            flags.hasFocus = conditions.hasFocus
            flags.isEditable = conditions.isEditable
            flags.isActiveParagraph = conditions.isActiveParagraph
            jest.mocked(isCurrentNodeEmpty).mockReturnValue(conditions.nodeEmpty)

            const { container } = renderComponent()

            expect(isSuggestionVisible(container)).toBe(expected)
        })

        it('re-evaluates visibility when the editor fires an update', () => {
            editorView = { dom: document.createElement('div') }
            flags.hasFocus = true
            flags.isEditable = true
            flags.isActiveParagraph = true
            jest.mocked(isCurrentNodeEmpty).mockReturnValue(true)

            const { container } = renderComponent()
            expect(isSuggestionVisible(container)).toBe(true)

            // Typing fills the node, so it should hide on the next editor update.
            jest.mocked(isCurrentNodeEmpty).mockReturnValue(false)
            act(() => {
                updateHandler?.()
            })

            expect(isSuggestionVisible(container)).toBe(false)
        })
    })
})
