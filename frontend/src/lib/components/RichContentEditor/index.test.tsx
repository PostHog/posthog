import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import StarterKit from '@tiptap/starter-kit'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { RichContentEditor } from './index'
import { JSONContent } from './types'

describe('RichContentEditor', () => {
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(jest.fn())
    })

    afterEach(() => {
        captureExceptionSpy.mockRestore()
    })

    function renderEditor(initialContent: JSONContent): void {
        render(
            <Provider>
                <RichContentEditor logicKey="test" extensions={[StarterKit]} initialContent={initialContent} />
            </Provider>
        )
    }

    it('renders valid stored content without capturing an error', () => {
        renderEditor({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hello' }] }],
        })

        expect(captureExceptionSpy).not.toHaveBeenCalled()
    })

    it('degrades gracefully when stored content references an unknown node type', () => {
        // Stored content referencing a node type absent from the configured extensions used to
        // throw synchronously while constructing the tiptap Editor, crashing the surrounding scene.
        expect(() =>
            renderEditor({
                type: 'doc',
                content: [{ type: 'totally-unknown-node', content: [{ type: 'text', text: 'boom' }] }],
            })
        ).not.toThrow()

        expect(captureExceptionSpy).toHaveBeenCalled()
    })
})
