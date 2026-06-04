import { act, fireEvent, render } from '@testing-library/react'
import { createElement } from 'react'

import { mergeNotebookMarkdownChanges } from './collaboration'
import {
    htmlElementToInlineNodes,
    parseMarkdownNotebook,
    serializeInlineNodes,
    serializeMarkdownNotebook,
} from './markdown'
import { MarkdownNotebook } from './MarkdownNotebook'
import { reconcileNotebookDocuments } from './reconcile'

describe('MarkdownNotebook', () => {
    it('round-trips supported markdown blocks and inline formatting', () => {
        const markdown = `# Heading

Paragraph with **bold**, *italic*, <u>underline</u>, \`code\`, and [link](https://posthog.com).

- One
- Two

> Quote`

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
    })

    it('parses and serializes JSX-like component tags', () => {
        const markdown = `<Query query={{"kind":"SavedInsightNode","shortId":"abc123"}} title="Activation" />`
        const document = parseMarkdownNotebook(markdown)

        expect(document.nodes[0]).toMatchObject({
            type: 'component',
            tagName: 'Query',
            props: {
                query: { kind: 'SavedInsightNode', shortId: 'abc123' },
                title: 'Activation',
            },
        })
        expect(serializeMarkdownNotebook(document)).toEqual(markdown)
    })

    it('preserves node identity for targeted text updates', () => {
        const previous = parseMarkdownNotebook(`Activation improved today.

Second paragraph stays stable.`)
        const next = parseMarkdownNotebook(`Activation improved today after launch.

Second paragraph stays stable.`)

        const reconciled = reconcileNotebookDocuments(previous, next)

        expect(reconciled.document.nodes[0].id).toEqual(previous.nodes[0].id)
        expect(reconciled.document.nodes[1].id).toEqual(previous.nodes[1].id)
        expect(reconciled.changes).toEqual([{ type: 'updated', nodeId: previous.nodes[0].id, index: 0 }])
    })

    it('sanitizes edited HTML into supported inline nodes', () => {
        const element = document.createElement('div')
        element.innerHTML = 'Hello <strong>bold</strong> <script>alert(1)</script><u>underlined</u>'

        expect(serializeInlineNodes(htmlElementToInlineNodes(element))).toEqual(
            'Hello **bold** alert(1)<u>underlined</u>'
        )
    })

    it('merges independent local and remote block edits', () => {
        const baseMarkdown = `# Activation

Activation improved today.`
        const localMarkdown = `# Activation

Activation improved today after launch.`
        const remoteMarkdown = `# Activation

Remote editor added a note.

Activation improved today.`

        const result = mergeNotebookMarkdownChanges({ baseMarkdown, localMarkdown, remoteMarkdown })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toContain('Remote editor added a note.')
        expect(result.mergedMarkdown).toContain('Activation improved today after launch.')
    })

    it('keeps local text and reports conflicts when both sides edit the same block', () => {
        const baseMarkdown = 'Activation improved today.'
        const localMarkdown = 'Activation improved locally.'
        const remoteMarkdown = 'Activation improved remotely.'

        const result = mergeNotebookMarkdownChanges({ baseMarkdown, localMarkdown, remoteMarkdown })

        expect(result.conflicts).toHaveLength(1)
        expect(result.mergedMarkdown).toEqual(localMarkdown)
    })

    it('keeps rapid text input stable while the editable DOM owns the active keystrokes', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]')

        expect(textBlock).toBeInstanceOf(HTMLElement)
        const editableTextBlock = textBlock as HTMLElement

        const typedValues = ['h', 'he', 'her', 'here', 'here is', 'here is another', 'here is another one']

        editableTextBlock.focus()
        typedValues.forEach((typedValue) => {
            editableTextBlock.textContent = typedValue
            fireEvent.input(editableTextBlock)
        })

        expect(onChange).toHaveBeenLastCalledWith('here is another one')
        expect(editableTextBlock.textContent).toEqual('here is another one')
    })

    it('floats and closes the formatting toolbar based on the active text selection', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'Select this text' }))
        const textBlock = container.querySelector('[contenteditable="true"]')

        expect(textBlock).toBeInstanceOf(HTMLElement)
        const editableTextBlock = textBlock as HTMLElement
        const selectedTextNode = editableTextBlock.firstChild

        expect(selectedTextNode).toBeInstanceOf(Text)

        const selectionRect = {
            bottom: 120,
            height: 20,
            left: 100,
            right: 180,
            top: 100,
            width: 80,
            x: 100,
            y: 100,
            toJSON: () => ({}),
        }
        const range = document.createRange()
        range.setStart(selectedTextNode as Text, 0)
        range.setEnd(selectedTextNode as Text, 6)
        Object.defineProperty(range, 'getBoundingClientRect', { value: () => selectionRect })
        Object.defineProperty(range, 'getClientRects', { value: () => [selectionRect] })

        act(() => {
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
            document.dispatchEvent(new Event('selectionchange'))
        })

        const toolbar = container.querySelector('.MarkdownNotebook__format-toolbar')
        expect(toolbar).toBeInstanceOf(HTMLElement)
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-left')).toEqual(
            '140px'
        )
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-top')).toEqual(
            '100px'
        )

        act(() => {
            window.getSelection()?.removeAllRanges()
            document.dispatchEvent(new Event('selectionchange'))
        })

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeNull()
    })
})
