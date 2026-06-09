import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { BindLogic } from 'kea'

import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { initKeaTests } from '~/test/init'

import { FloatingSuggestions } from './FloatingSuggestions'

jest.mock('lib/hooks/useResizeObserver', () => ({
    useResizeObserver: jest.fn(),
}))

describe('FloatingSuggestions', () => {
    const setRef = jest.fn()
    let mountHandler: (() => void) | undefined
    let editorView: { dom: HTMLElement } | null

    // In tiptap v3 `editor.view` is a throwing proxy until the ProseMirror view mounts, so the
    // component reads `editorView` (via getTiptapEditorDom) and binds the observer on the 'mount' event.
    const fakeEditor = {
        on: jest.fn((event: string, cb: () => void) => {
            if (event === 'mount') {
                mountHandler = cb
            }
        }),
        off: jest.fn(),
        isDestroyed: false,
        isEditable: false,
        isActive: () => false,
        view: { hasFocus: () => false },
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

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mountHandler = undefined
        editorView = null
        jest.mocked(useResizeObserver).mockReturnValue({ ref: setRef, height: 0 } as any)
    })

    afterEach(() => {
        cleanup()
    })

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
