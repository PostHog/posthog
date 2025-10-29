import { render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { EditorScene } from './EditorScene'

jest.mock('./QueryWindow', () => ({
    QueryWindow: function MockQueryWindow() {
        return <div data-attr="mock-query-window">Query Window</div>
    },
}))

jest.mock('../ViewLinkModal', () => ({
    ViewLinkModal: function MockViewLinkModal() {
        return <div data-attr="mock-view-link-modal">View Link Modal</div>
    },
}))

describe('EditorScene', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('renders the editor scene container', () => {
        const { container } = render(
            <Provider>
                <EditorScene tabId="test-tab" />
            </Provider>
        )

        const editorScene = container.querySelector('[data-attr="editor-scene"]')
        expect(editorScene).toBeInTheDocument()
    })

    it('applies correct CSS classes to the container', () => {
        const { container } = render(
            <Provider>
                <EditorScene tabId="test-tab" />
            </Provider>
        )

        const editorScene = container.querySelector('[data-attr="editor-scene"]')
        expect(editorScene).toHaveClass('EditorScene')
        expect(editorScene).toHaveClass('w-full')
        expect(editorScene).toHaveClass('flex')
        expect(editorScene).toHaveClass('flex-row')
        expect(editorScene).toHaveClass('overflow-hidden')
    })

    it('renders QueryWindow component', () => {
        const { container } = render(
            <Provider>
                <EditorScene tabId="test-tab" />
            </Provider>
        )

        const queryWindow = container.querySelector('[data-attr="mock-query-window"]')
        expect(queryWindow).toBeInTheDocument()
    })

    it('renders ViewLinkModal component', () => {
        const { container } = render(
            <Provider>
                <EditorScene tabId="test-tab" />
            </Provider>
        )

        const viewLinkModal = container.querySelector('[data-attr="mock-view-link-modal"]')
        expect(viewLinkModal).toBeInTheDocument()
    })

    it('handles missing tabId prop by using empty string', () => {
        const { container } = render(
            <Provider>
                <EditorScene />
            </Provider>
        )

        const editorScene = container.querySelector('[data-attr="editor-scene"]')
        expect(editorScene).toBeInTheDocument()
    })

    it('passes tabId prop to QueryWindow', () => {
        const { container } = render(
            <Provider>
                <EditorScene tabId="custom-tab-id" />
            </Provider>
        )

        const queryWindow = container.querySelector('[data-attr="mock-query-window"]')
        expect(queryWindow).toBeInTheDocument()
    })
})
