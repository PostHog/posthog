import { act, fireEvent, render, waitFor } from '@testing-library/react'
import { createElement, useEffect } from 'react'

import { mergeNotebookMarkdownChanges } from './collaboration'
import {
    htmlElementToInlineNodes,
    inlineNodesToHtml,
    parseMarkdownNotebook,
    serializeInlineNodes,
    serializeMarkdownNotebook,
} from './markdown'
import { MarkdownNotebook } from './MarkdownNotebook'
import { reconcileNotebookDocuments } from './reconcile'
import { createMarkdownNotebookRegistry } from './registry'

function getFirstTextNode(element: HTMLElement): Text {
    const textNode = document.createTreeWalker(element, NodeFilter.SHOW_TEXT).nextNode()

    expect(textNode).toBeInstanceOf(Text)

    return textNode as Text
}

function selectTextInElement(element: HTMLElement, start: number, end: number): void {
    selectTextNode(getFirstTextNode(element), start, end)
}

function selectElementContents(element: HTMLElement): void {
    act(() => {
        const range = document.createRange()
        range.selectNodeContents(element)
        const selection = window.getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
    })
}

function selectAroundElement(element: HTMLElement): void {
    act(() => {
        const range = document.createRange()
        range.setStartBefore(element)
        range.setEndAfter(element)
        const selection = window.getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
    })
}

function selectTextNode(textNode: Text, start: number, end: number, showToolbar = false): void {
    act(() => {
        const range = document.createRange()
        range.setStart(textNode, start)
        range.setEnd(textNode, end)
        if (showToolbar) {
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
            Object.defineProperty(range, 'getBoundingClientRect', { value: () => selectionRect })
            Object.defineProperty(range, 'getClientRects', { value: () => [selectionRect] })
        }
        const selection = window.getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
        if (showToolbar) {
            document.dispatchEvent(new Event('selectionchange'))
        }
    })
}

function pastePlainText(element: HTMLElement, text: string): void {
    fireEvent.paste(element, {
        clipboardData: {
            getData: jest.fn((type: string) => (type === 'text/plain' ? text : '')),
        },
    })
}

function fireHistoryBeforeInput(element: HTMLElement, inputType: 'historyUndo' | 'historyRedo'): void {
    const event = new Event('beforeinput', { bubbles: true, cancelable: true }) as InputEvent
    Object.defineProperty(event, 'inputType', { value: inputType })
    fireEvent(element, event)
}

describe('MarkdownNotebook', () => {
    it('round-trips supported markdown blocks and inline formatting', () => {
        const markdown = `# Heading

Paragraph with **bold**, *italic*, <u>underline</u>, \`code\`, and [link](https://posthog.com).

- One
- Two

> Quote`

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
    })

    it('preserves literal backslashes when serializing markdown text', () => {
        const markdown = String.raw`Path C:\\Users\\marius and regex \\d+

- Keep C:\\Temp

| Pattern |
| --- |
| \\w+ |`

        const onceSerialized = serializeMarkdownNotebook(parseMarkdownNotebook(markdown))

        expect(onceSerialized).toEqual(markdown)
        expect(serializeMarkdownNotebook(parseMarkdownNotebook(onceSerialized))).toEqual(markdown)
    })

    it('strips unsafe protocols from markdown links', () => {
        const document = parseMarkdownNotebook(
            'Safe [link](https://posthog.com), unsafe [link](javascript:alert), relative [link](/project), and mail [link](mailto:test@example.com).'
        )
        const node = document.nodes[0]

        expect(serializeMarkdownNotebook(document)).toEqual(
            'Safe [link](https://posthog.com), unsafe link, relative link, and mail link.'
        )
        expect(node.type).toEqual('paragraph')
        if (node.type !== 'paragraph') {
            throw new Error('Expected paragraph node')
        }
        expect(inlineNodesToHtml(node.children)).toEqual(
            'Safe <a href="https://posthog.com">link</a>, unsafe link, relative link, and mail link.'
        )
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

    it('round-trips component string props with reversible escaping', () => {
        const props = {
            src: 'https://posthog.com/embed?one=1&two=2',
            title: 'A "quoted" <embed> & title',
            latex: 'E = mc^2 & x < y',
        }
        const markdown = `<Embed src=${JSON.stringify(props.src)} title=${JSON.stringify(props.title)} latex=${JSON.stringify(props.latex)} />`
        const document = parseMarkdownNotebook(markdown)

        expect(document.nodes[0]).toMatchObject({
            type: 'component',
            tagName: 'Embed',
            props,
        })
        expect(serializeMarkdownNotebook(document)).toEqual(markdown)
        expect(serializeMarkdownNotebook(parseMarkdownNotebook(serializeMarkdownNotebook(document)))).toEqual(markdown)
    })

    it('decodes legacy HTML entities in component string props', () => {
        const markdown =
            '<Embed src="https://posthog.com/embed?one=1&amp;two=2" title="A &quot;quoted&quot; &lt;embed&gt; &amp; title" />'
        const expectedMarkdown = `<Embed src=${JSON.stringify('https://posthog.com/embed?one=1&two=2')} title=${JSON.stringify('A "quoted" <embed> & title')} />`
        const document = parseMarkdownNotebook(markdown)

        expect(document.nodes[0]).toMatchObject({
            type: 'component',
            tagName: 'Embed',
            props: {
                src: 'https://posthog.com/embed?one=1&two=2',
                title: 'A "quoted" <embed> & title',
            },
        })
        expect(serializeMarkdownNotebook(document)).toEqual(expectedMarkdown)
        expect(serializeMarkdownNotebook(parseMarkdownNotebook(expectedMarkdown))).toEqual(expectedMarkdown)
    })

    it('round-trips markdown image blocks as image components', () => {
        const markdown = '![PostHog engineering](https://res.cloudinary.com/demo/image/upload/posthog.png)'
        const document = parseMarkdownNotebook(markdown)

        expect(document.nodes[0]).toMatchObject({
            type: 'component',
            tagName: 'Image',
            props: {
                alt: 'PostHog engineering',
                src: 'https://res.cloudinary.com/demo/image/upload/posthog.png',
            },
        })
        expect(serializeMarkdownNotebook(document)).toEqual(markdown)
    })

    it('serializes legacy Image component tags as markdown image blocks', () => {
        expect(
            serializeMarkdownNotebook(
                parseMarkdownNotebook(
                    '<Image src="https://res.cloudinary.com/demo/image/upload/posthog.png" alt="PostHog engineering" />'
                )
            )
        ).toEqual('![PostHog engineering](https://res.cloudinary.com/demo/image/upload/posthog.png)')
    })

    it('round-trips nested markdown lists', () => {
        const markdown = `- Parent
  - Child
    - Grandchild
- Sibling

1. First
  1. Nested first
2. Second`

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
    })

    it('parses empty markdown list markers as list items', () => {
        expect(serializeMarkdownNotebook(parseMarkdownNotebook('-'))).toEqual('-')
        expect(serializeMarkdownNotebook(parseMarkdownNotebook('1.'))).toEqual('1.')
    })

    it('round-trips intentional blank paragraph placeholders', () => {
        expect(serializeMarkdownNotebook(parseMarkdownNotebook('Intro paragraph\n\n '))).toEqual('Intro paragraph\n\n ')
        expect(serializeMarkdownNotebook(parseMarkdownNotebook(' \n\nIntro paragraph'))).toEqual(' \n\nIntro paragraph')
        expect(serializeMarkdownNotebook(parseMarkdownNotebook(' '))).toEqual('')
    })

    it('round-trips markdown tables', () => {
        const markdown = `| Name | Count | Ratio |
| :--- | ---: | :---: |
| Pageview | **12** | 10% |
| Signup | 3 | 2% |`

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
    })

    it('round-trips single-column markdown tables', () => {
        const markdown = `| Column 1 |
| --- |
| ewfwef |
| efaew |`

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(markdown)
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

    it('strips unsafe protocols from pasted HTML links', () => {
        const element = document.createElement('div')
        element.innerHTML =
            'Safe <a href="https://posthog.com">link</a> unsafe <a href="javascript:alert">link</a> relative <a href="/project">link</a>'
        const inlineNodes = htmlElementToInlineNodes(element)

        expect(serializeInlineNodes(inlineNodes)).toEqual('Safe [link](https://posthog.com) unsafe link relative link')
        expect(inlineNodesToHtml(inlineNodes)).toEqual(
            'Safe <a href="https://posthog.com">link</a> unsafe link relative link'
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

    it('undoes and redoes notebook text edits with keyboard shortcuts', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]')

        expect(textBlock).toBeInstanceOf(HTMLElement)
        const editableTextBlock = textBlock as HTMLElement

        editableTextBlock.focus()
        editableTextBlock.textContent = 'hello'
        fireEvent.input(editableTextBlock)
        editableTextBlock.textContent = 'hello world'
        fireEvent.input(editableTextBlock)

        fireEvent.keyDown(editableTextBlock, { key: 'z', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith('hello')
        expect(editableTextBlock.textContent).toEqual('hello')
        expect(document.activeElement).toEqual(editableTextBlock)

        fireEvent.keyDown(editableTextBlock, { key: 'z', metaKey: true, shiftKey: true })

        expect(onChange).toHaveBeenLastCalledWith('hello world')
        expect(editableTextBlock.textContent).toEqual('hello world')

        fireEvent.keyDown(editableTextBlock, { key: 'z', ctrlKey: true })

        expect(onChange).toHaveBeenLastCalledWith('hello')
        expect(editableTextBlock.textContent).toEqual('hello')

        fireEvent.keyDown(editableTextBlock, { key: 'y', ctrlKey: true })

        expect(onChange).toHaveBeenLastCalledWith('hello world')
        expect(editableTextBlock.textContent).toEqual('hello world')
    })

    it('does not re-render unchanged components when the value prop updates another block', () => {
        const renderComponent = jest.fn()
        const mountComponent = jest.fn()
        const unmountComponent = jest.fn()
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Embed',
                label: 'Embed',
                category: 'Media',
                ViewComponent: () => {
                    renderComponent()
                    useEffect(() => {
                        mountComponent()
                        return () => unmountComponent()
                    }, [])
                    return createElement('div', { 'data-testid': 'stable-embed' })
                },
            },
        ])
        const initialMarkdown = `# Embeds

<Embed src="https://posthog.com" title="PostHog" />`
        const { rerender } = render(createElement(MarkdownNotebook, { value: initialMarkdown, registry }))

        rerender(
            createElement(MarkdownNotebook, {
                value: `# Updated embeds

<Embed src="https://posthog.com" title="PostHog" />`,
                registry,
            })
        )

        expect(renderComponent).toHaveBeenCalledTimes(1)
        expect(mountComponent).toHaveBeenCalledTimes(1)
        expect(unmountComponent).not.toHaveBeenCalled()
    })

    it('does not remount a newly inserted component when the matching remote save arrives', () => {
        const onChange = jest.fn()
        const renderComponent = jest.fn()
        const mountComponent = jest.fn()
        const unmountComponent = jest.fn()
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Embed',
                label: 'Embed',
                category: 'Media',
                defaultProps: { src: 'https://posthog.com', title: 'PostHog' },
                ViewComponent: () => {
                    renderComponent()
                    useEffect(() => {
                        mountComponent()
                        return () => unmountComponent()
                    }, [])
                    return createElement('div', { 'data-testid': 'stable-embed' })
                },
            },
        ])
        const { container, rerender } = render(
            createElement(MarkdownNotebook, { value: '', remoteValue: '', onChange, registry })
        )
        const row = container.querySelector('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        editableTextBlock.textContent = 'iframe'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        const savedMarkdown = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(savedMarkdown).toEqual('<Embed src="https://posthog.com" title="PostHog" />')

        const renderCountBeforeRemoteSave = renderComponent.mock.calls.length
        const mountCountBeforeRemoteSave = mountComponent.mock.calls.length
        const unmountCountBeforeRemoteSave = unmountComponent.mock.calls.length
        rerender(
            createElement(MarkdownNotebook, { value: savedMarkdown, remoteValue: savedMarkdown, onChange, registry })
        )

        expect(renderComponent).toHaveBeenCalledTimes(renderCountBeforeRemoteSave)
        expect(mountComponent).toHaveBeenCalledTimes(mountCountBeforeRemoteSave)
        expect(unmountComponent).toHaveBeenCalledTimes(unmountCountBeforeRemoteSave)
    })

    it('defers remote markdown updates while requested', () => {
        const { container, rerender } = render(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: 'Local text',
                deferRemoteValue: true,
            })
        )

        rerender(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: 'Remote text',
                deferRemoteValue: true,
            })
        )

        expect(container.querySelector('.MarkdownNotebook__text-block')?.textContent).toEqual('Local text')

        rerender(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: 'Remote text',
                deferRemoteValue: false,
            })
        )

        expect(container.querySelector('.MarkdownNotebook__text-block')?.textContent).toEqual('Remote text')
    })

    it('applies empty remote markdown updates', () => {
        const { container, rerender } = render(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: 'Local text',
            })
        )

        rerender(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: '',
            })
        )

        expect(container.querySelector('.MarkdownNotebook__text-block')?.textContent).toEqual('')
    })

    it('applies deferred empty remote markdown updates', () => {
        const { container, rerender } = render(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: 'Local text',
                deferRemoteValue: true,
            })
        )

        rerender(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: '',
                deferRemoteValue: true,
            })
        )

        expect(container.querySelector('.MarkdownNotebook__text-block')?.textContent).toEqual('Local text')

        rerender(
            createElement(MarkdownNotebook, {
                value: 'Local text',
                remoteValue: '',
                deferRemoteValue: false,
            })
        )

        expect(container.querySelector('.MarkdownNotebook__text-block')?.textContent).toEqual('')
    })

    it('marks interaction active before clearing slash command text', () => {
        const onChange = jest.fn()
        const onInteractionStateChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange, onInteractionStateChange }))
        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        editableTextBlock.textContent = '/'
        fireEvent.input(editableTextBlock)

        const firstActiveInteractionCall = onInteractionStateChange.mock.calls.findIndex(([isActive]) => isActive)

        expect(firstActiveInteractionCall).toBeGreaterThanOrEqual(0)
        expect(onChange).toHaveBeenCalledWith('')
        expect(onInteractionStateChange.mock.invocationCallOrder[firstActiveInteractionCall]).toBeLessThan(
            onChange.mock.invocationCallOrder[0]
        )
    })

    it('only shows the writing placeholder for an empty notebook', () => {
        const { container: emptyContainer } = render(createElement(MarkdownNotebook, { value: '' }))

        expect(emptyContainer.querySelectorAll('[data-placeholder="Start writing..."]')).toHaveLength(1)

        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph' }))
        const textBlock = container.querySelector('[contenteditable="true"]')

        expect(textBlock).toBeInstanceOf(HTMLElement)
        fireEvent.keyDown(textBlock as HTMLElement, { key: 'Enter' })

        expect(container.querySelectorAll('[data-placeholder="Start writing..."]')).toHaveLength(0)
    })

    it('opens a synced markdown debug drawer when enabled', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph', showDebug: true }))
        const debugButton = Array.from(container.querySelectorAll('button')).find((button) =>
            button.textContent?.includes('Debug')
        )

        expect(debugButton).toBeInstanceOf(HTMLButtonElement)
        expect(container.querySelector('.MarkdownNotebook__debug-drawer')).toBeNull()

        fireEvent.click(debugButton as HTMLButtonElement)

        const debugTextarea = container.querySelector('.MarkdownNotebook__debug-markdown') as HTMLTextAreaElement
        expect(container.querySelector('.MarkdownNotebook__debug-drawer')).toBeInstanceOf(HTMLElement)
        expect(debugTextarea).toBeInstanceOf(HTMLTextAreaElement)
        expect(debugTextarea.value).toEqual('First paragraph')

        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        editableTextBlock.textContent = 'Updated paragraph'
        fireEvent.input(editableTextBlock)

        expect(debugTextarea.value).toEqual('Updated paragraph')

        fireEvent.change(debugTextarea, { target: { value: '# Edited from debug' } })

        expect(debugTextarea.value).toEqual('# Edited from debug')
        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('Edited from debug')

        const closeButton = Array.from(container.querySelectorAll('.MarkdownNotebook__debug-drawer button')).find(
            (button) => button.textContent?.includes('Close')
        )
        expect(closeButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(closeButton as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__debug-drawer')).toBeNull()
    })

    it('uses the boundary add button to insert a blank row after populated rows', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Intro paragraph', onChange }))
        const boundaryButtons = Array.from(
            container.querySelectorAll('.MarkdownNotebook__insert-boundary-button')
        ) as HTMLButtonElement[]
        const addAfterButton = boundaryButtons[1]

        expect(boundaryButtons).toHaveLength(2)
        fireEvent.click(addAfterButton)

        expect(container.querySelector('.MarkdownNotebook__row--insert-menu-open')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph\n\n ')
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const slashTextBlock = textBlocks[1]
        expect(document.activeElement).toEqual(slashTextBlock)
        expect(slashTextBlock.textContent).toEqual('')
        expect(container.querySelectorAll('.MarkdownNotebook__insert-boundary-button')).toHaveLength(1)
        const lineInsertMenuButton = container.querySelector('.MarkdownNotebook__line-insert-menu-button')
        expect(lineInsertMenuButton).toBeInstanceOf(HTMLButtonElement)
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()

        fireEvent.click(lineInsertMenuButton as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__row--insert-menu-open')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__line-insert-menu-button')).toBeInstanceOf(HTMLButtonElement)
        expect(
            container.querySelector('.MarkdownNotebook__line-insert-menu-button')?.getAttribute('aria-expanded')
        ).toEqual('true')
        expect(slashTextBlock.getAttribute('data-placeholder')).toEqual('Search for a tool')

        const initialInsertItems = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item'))
        expect(container.querySelector('.MarkdownNotebook__insert-menu')?.textContent).not.toContain('Add to notebook')
        expect(initialInsertItems[0].textContent).toEqual('Trend')
        expect(initialInsertItems[0].getAttribute('aria-selected')).toEqual('true')
        expect(initialInsertItems.map((item) => item.textContent)).not.toContain('Text')
        expect(initialInsertItems.map((item) => item.textContent)).not.toContain('Feature flag')

        slashTextBlock.textContent = 'zzzz'
        fireEvent.input(slashTextBlock)
        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph\n\nzzzz')

        expect(container.querySelector('.MarkdownNotebook__empty-menu')?.textContent).toEqual('No components found')

        fireEvent.keyDown(slashTextBlock, { key: 'Enter' })
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph\n\n ')
        expect(document.activeElement).toEqual(slashTextBlock)
        expect(slashTextBlock.textContent).toEqual('')

        slashTextBlock.textContent = 'tr'
        fireEvent.input(slashTextBlock)
        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph\n\ntr')

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)

        const filteredInsertItems = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item'))
        expect(filteredInsertItems[0].textContent).toEqual('Trend')
        expect(filteredInsertItems[0].getAttribute('aria-selected')).toEqual('true')

        const trendButton = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item')).find(
            (button) => button.textContent === 'Trend'
        )

        expect(trendButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(trendButton as HTMLButtonElement)

        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining('Intro paragraph\n\n<Query'))
        expect(container.querySelector('.MarkdownNotebook__component-edit')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__component-preview')).toBeInstanceOf(HTMLElement)
    })

    it('keeps inserted blank rows after receiving the serialized markdown value', () => {
        const onChange = jest.fn()
        const { container, rerender } = render(createElement(MarkdownNotebook, { value: 'Intro paragraph', onChange }))
        const addAfterButton = Array.from(
            container.querySelectorAll('.MarkdownNotebook__insert-boundary-button')
        )[1] as HTMLButtonElement

        fireEvent.click(addAfterButton)

        const nextValue = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as string
        rerender(createElement(MarkdownNotebook, { value: nextValue, onChange }))

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        expect(nextValue).toEqual('Intro paragraph\n\n ')
        expect(textBlocks).toHaveLength(2)
        expect(textBlocks[1].textContent).toEqual('')
    })

    it('adds and focuses a trailing blank row when clicking below the notebook canvas', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Intro paragraph', onChange }))
        const main = container.querySelector('.MarkdownNotebook__main') as HTMLElement
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement

        Object.defineProperty(canvas, 'getBoundingClientRect', {
            configurable: true,
            value: () => ({
                bottom: 100,
                height: 50,
                left: 0,
                right: 500,
                top: 50,
                width: 500,
                x: 0,
                y: 50,
                toJSON: () => ({}),
            }),
        })

        fireEvent.mouseDown(main, { button: 0, clientY: 140 })

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph\n\n ')
        expect(textBlocks).toHaveLength(2)
        expect(document.activeElement).toEqual(textBlocks[1])
    })

    it('renders one boundary add button per gap', () => {
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
            })
        )
        const rows = Array.from(container.querySelectorAll('.MarkdownNotebook__row'))
        const boundaryButtons = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-boundary-button'))

        expect(rows).toHaveLength(2)
        expect(boundaryButtons).toHaveLength(3)
    })

    it('only reveals the closest boundary add button while hovering populated rows', () => {
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph

Third paragraph`,
            })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas')
        const rows = Array.from(container.querySelectorAll('.MarkdownNotebook__row'))
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const setRowRect = (row: Element, top: number, height: number): void => {
            Object.defineProperty(row, 'getBoundingClientRect', {
                configurable: true,
                value: () => ({
                    bottom: top + height,
                    height,
                    left: 0,
                    right: 500,
                    top,
                    width: 500,
                    x: 0,
                    y: top,
                    toJSON: () => ({}),
                }),
            })
        }
        const getVisibleBoundaryIndexes = (): string[] =>
            Array.from(container.querySelectorAll('.MarkdownNotebook__insert-boundary-button--visible')).map(
                (button) => (button as HTMLElement).dataset.boundaryIndex ?? ''
            )

        expect(canvas).toBeInstanceOf(HTMLElement)
        expect(rows).toHaveLength(3)
        expect(textBlocks).toHaveLength(3)
        expect(getVisibleBoundaryIndexes()).toEqual([])
        setRowRect(rows[0], 0, 100)
        setRowRect(rows[1], 100, 100)

        fireEvent.mouseEnter(rows[1], { clientY: 120 })
        expect(getVisibleBoundaryIndexes()).toEqual(['1'])

        fireEvent.mouseMove(rows[1], { clientY: 180 })
        expect(getVisibleBoundaryIndexes()).toEqual(['2'])

        fireEvent.focus(textBlocks[1])
        expect(getVisibleBoundaryIndexes()).toEqual([])

        fireEvent.blur(textBlocks[1])
        fireEvent.mouseMove(rows[1], { clientY: 180 })
        expect(getVisibleBoundaryIndexes()).toEqual(['2'])

        fireEvent.mouseEnter(rows[0], { clientY: 75 })
        expect(getVisibleBoundaryIndexes()).toEqual(['1'])

        fireEvent.mouseLeave(canvas as HTMLElement)
        expect(getVisibleBoundaryIndexes()).toEqual([])
    })

    it('uses a line menu button for empty notebooks instead of boundary add buttons', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const row = container.querySelector('.MarkdownNotebook__row')
        const lineInsertMenuButton = container.querySelector('.MarkdownNotebook__line-insert-menu-button')
        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        expect(row).toBeInstanceOf(HTMLElement)
        expect(editableTextBlock).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__insert-boundary-button')).toBeNull()
        expect(lineInsertMenuButton).toBeInstanceOf(HTMLButtonElement)
        expect(lineInsertMenuButton?.textContent).toEqual('/')
        expect(lineInsertMenuButton?.querySelector('.MarkdownNotebook__line-insert-menu-icon')).toBeInstanceOf(
            HTMLElement
        )
        expect(lineInsertMenuButton?.closest('.MarkdownNotebook__text-row--inline-menu-visible')).toBeNull()
        expect(lineInsertMenuButton?.getAttribute('tabindex')).toEqual('-1')

        fireEvent.mouseEnter(row as HTMLElement)

        expect(lineInsertMenuButton?.closest('.MarkdownNotebook__text-row--inline-menu-visible')).toBeInstanceOf(
            HTMLElement
        )
        expect(lineInsertMenuButton?.getAttribute('tabindex')).toEqual('0')

        fireEvent.click(lineInsertMenuButton as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__line-insert-menu-button')).toBeInstanceOf(HTMLButtonElement)
        expect(
            container.querySelector('.MarkdownNotebook__line-insert-menu-button')?.getAttribute('aria-expanded')
        ).toEqual('true')
        expect(
            container
                .querySelector('.MarkdownNotebook__line-insert-menu-button')
                ?.classList.contains('LemonButton--active')
        ).toBe(true)
        expect(container.querySelector('[data-placeholder="Search for a tool"]')).toBeInstanceOf(HTMLElement)
        expect(editableTextBlock.classList.contains('MarkdownNotebook__text-block--insert-placeholder')).toBe(true)
        expect(container.querySelector('[data-placeholder="Start writing..."]')).toBeNull()
        expect(document.activeElement).toEqual(editableTextBlock)

        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()
        expect(container.querySelector('[data-placeholder="Start writing..."]')).toBeInstanceOf(HTMLElement)
        expect(
            container
                .querySelector('.MarkdownNotebook__line-insert-menu-button')
                ?.classList.contains('LemonButton--active')
        ).toBe(false)
        expect(document.activeElement).toEqual(editableTextBlock)

        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('[data-placeholder="Search for a tool"]')).toBeInstanceOf(HTMLElement)

        expect(document.activeElement).toEqual(editableTextBlock)

        editableTextBlock.textContent = '/'
        fireEvent.input(editableTextBlock)

        expect(editableTextBlock.textContent).toEqual('')
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()

        fireEvent.mouseLeave(container.querySelector('.MarkdownNotebook__canvas') as HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__line-insert-menu-button')).toBeInstanceOf(HTMLButtonElement)
        expect(
            container
                .querySelector('.MarkdownNotebook__line-insert-menu-button')
                ?.closest('.MarkdownNotebook__text-row--inline-menu-visible')
        ).toBeNull()

        fireEvent.focus(editableTextBlock)
        expect(
            container
                .querySelector('.MarkdownNotebook__line-insert-menu-button')
                ?.closest('.MarkdownNotebook__text-row--inline-menu-visible')
        ).toBeInstanceOf(HTMLElement)

        editableTextBlock.textContent = '/'
        fireEvent.input(editableTextBlock)

        expect(editableTextBlock.textContent).toEqual('')
        expect(container.querySelector('.MarkdownNotebook__line-insert-menu-button')).toBeInstanceOf(HTMLButtonElement)
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)

        editableTextBlock.textContent = 'zzzz'
        fireEvent.input(editableTextBlock)

        expect(editableTextBlock.classList.contains('MarkdownNotebook__text-block--invalid-insert-filter')).toBe(true)
        expect(container.querySelector('.MarkdownNotebook__empty-menu')?.textContent).toEqual('No components found')

        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        expect(editableTextBlock.textContent).toEqual('')
        expect(editableTextBlock.classList.contains('MarkdownNotebook__text-block--invalid-insert-filter')).toBe(false)
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)

        editableTextBlock.textContent = 'tr'
        fireEvent.input(editableTextBlock)

        const filteredInsertItems = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item'))
        expect(filteredInsertItems[0].textContent).toEqual('Trend')
        expect(filteredInsertItems[0].getAttribute('aria-selected')).toEqual('true')
        expect(filteredInsertItems[0].querySelector('.MarkdownNotebook__insert-item-highlight')?.textContent).toEqual(
            'Tr'
        )

        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining('TrendsQuery'))
    })

    it('clears the slash command query with Cmd+A then Backspace', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const row = container.querySelector('.MarkdownNotebook__row')

        expect(row).toBeInstanceOf(HTMLElement)
        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        textBlock.textContent = 'zzzz'
        fireEvent.input(textBlock)

        expect(textBlock.textContent).toEqual('zzzz')
        expect(container.querySelector('.MarkdownNotebook__empty-menu')?.textContent).toEqual('No components found')

        fireEvent.keyDown(textBlock, { key: 'a', metaKey: true })
        fireEvent.keyDown(textBlock, { key: 'Backspace' })

        const lineInsertMenuButton = container.querySelector('.MarkdownNotebook__line-insert-menu-button')
        expect(textBlock.textContent).toEqual('')
        expect(document.activeElement).toEqual(textBlock)
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__empty-menu')).toBeNull()
        expect(lineInsertMenuButton?.getAttribute('aria-expanded')).toEqual('true')
        expect(lineInsertMenuButton?.classList.contains('LemonButton--active')).toBe(true)
        expect(onChange).toHaveBeenLastCalledWith('')
    })

    it('closes the slash menu when clicking outside it', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: '' }))
        const row = container.querySelector('.MarkdownNotebook__row')

        expect(row).toBeInstanceOf(HTMLElement)
        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const insertMenu = container.querySelector('.MarkdownNotebook__insert-menu')
        expect(insertMenu).toBeInstanceOf(HTMLElement)

        fireEvent.pointerDown(insertMenu as HTMLElement)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)

        fireEvent.pointerDown(window.document.body)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()
    })

    it('moves slash menu selection with arrow keys', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const row = container.querySelector('.MarkdownNotebook__row')

        expect(row).toBeInstanceOf(HTMLElement)
        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        const getSelectedLabel = (): string | null =>
            container.querySelector('.MarkdownNotebook__insert-item[aria-selected="true"]')?.textContent ?? null

        expect(getSelectedLabel()).toEqual('Trend')

        fireEvent.keyDown(textBlock, { key: 'ArrowDown' })

        expect(getSelectedLabel()).toEqual('Funnel')

        fireEvent.keyDown(textBlock, { key: 'ArrowDown' })

        expect(getSelectedLabel()).toEqual('Saved insight')

        fireEvent.keyDown(textBlock, { key: 'ArrowUp' })

        expect(getSelectedLabel()).toEqual('Funnel')

        fireEvent.keyDown(textBlock, { key: 'Enter' })

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining('FunnelsQuery'))
    })

    it('shows Ask PostHog AI first when AI is enabled and submits from the inline prompt', () => {
        const onAskAI = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onAskAI }))
        const row = container.querySelector('.MarkdownNotebook__row')

        expect(row).toBeInstanceOf(HTMLElement)
        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const insertCategories = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-category'))
        const firstInsertItem = container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement

        expect(insertCategories[0].querySelector('h5')?.textContent).toEqual('AI')
        expect(firstInsertItem.textContent).toEqual('Ask PostHog AI')
        expect(firstInsertItem.getAttribute('aria-selected')).toEqual('true')

        fireEvent.click(firstInsertItem)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()
        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.textContent).toEqual('Ask AI')

        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.textContent).toEqual('Thinking ...')
        expect(container.querySelector('.MarkdownNotebook__line-insert-menu-button')).toBeNull()
        const aiRequest = onAskAI.mock.calls[0][0]

        expect(aiRequest).toEqual({
            query: 'Add a summary here',
            placeholderNodeId: expect.any(String),
            insertionPlaceholder: expect.any(String),
            markdown: '',
            markdownWithPlaceholder: expect.any(String),
        })
        expect(aiRequest.insertionPlaceholder).toEqual(
            `<!-- Ask PostHog AI insertion placeholder block id: ${aiRequest.placeholderNodeId} -->`
        )
        expect(aiRequest.markdownWithPlaceholder).toEqual(aiRequest.insertionPlaceholder)
    })

    it('removes a stuck AI thinking placeholder when selected and deleted', () => {
        const onAskAI = jest.fn()
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onAskAI, onChange }))
        const row = container.querySelector('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        const thinkingTag = container.querySelector('.MarkdownNotebook__ai-prompt-tag') as HTMLButtonElement

        expect(thinkingTag.textContent).toEqual('Thinking ...')

        fireEvent.click(thinkingTag)
        fireEvent.keyDown(thinkingTag, { key: 'Backspace' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith('')
        expect(document.activeElement).toEqual(container.querySelector('[contenteditable="true"]'))
        expect(window.getSelection()?.focusOffset).toEqual(0)
    })

    it('applies remote markdown updates while showing an AI thinking placeholder', async () => {
        const onAskAI = jest.fn()
        const onInteractionStateChange = jest.fn()
        const { container, rerender } = render(
            createElement(MarkdownNotebook, {
                value: '',
                remoteValue: '',
                onAskAI,
                onInteractionStateChange,
            })
        )
        const row = container.querySelector('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.textContent).toEqual('Thinking ...')
        expect(onInteractionStateChange).toHaveBeenLastCalledWith(false)

        rerender(
            createElement(MarkdownNotebook, {
                value: '',
                remoteValue: 'AI response',
                onAskAI,
                onInteractionStateChange,
            })
        )

        await waitFor(() => {
            if (container.querySelector('.MarkdownNotebook__ai-prompt-tag')) {
                throw new Error('Expected AI prompt tag to be removed')
            }
        })
        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('AI response')
    })

    it('moves focus through an AI thinking placeholder and deletes it from keyboard focus', () => {
        const onAskAI = jest.fn()
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `Before

 

After`,
                onAskAI,
                onChange,
            })
        )
        const initialTextBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]

        expect(initialTextBlocks.map((block) => block.textContent)).toEqual(['Before', '', 'After'])

        initialTextBlocks[1].textContent = '/'
        fireEvent.input(initialTextBlocks[1])
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        initialTextBlocks[1].textContent = 'Add a summary here'
        fireEvent.input(initialTextBlocks[1])
        fireEvent.keyDown(initialTextBlocks[1], { key: 'Enter' })

        const thinkingTag = container.querySelector('.MarkdownNotebook__ai-prompt-tag') as HTMLButtonElement
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]

        expect(thinkingTag.textContent).toEqual('Thinking ...')
        expect(textBlocks.map((block) => block.textContent)).toEqual(['Before', 'After'])

        selectTextInElement(textBlocks[0], 0, 0)
        fireEvent.keyDown(textBlocks[0], { key: 'ArrowDown' })

        expect(document.activeElement).toEqual(thinkingTag)

        fireEvent.keyDown(thinkingTag, { key: 'ArrowDown' })

        expect(document.activeElement).toEqual(textBlocks[1])

        selectTextInElement(textBlocks[1], 0, 0)
        fireEvent.keyDown(textBlocks[1], { key: 'ArrowUp' })

        expect(document.activeElement).toEqual(thinkingTag)

        fireEvent.keyDown(thinkingTag, { key: 'Backspace' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')).toBeNull()
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`Before

After`)
    })

    it('creates a blank row below an AI thinking placeholder when clicking below the canvas', () => {
        const onAskAI = jest.fn()
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onAskAI, onChange }))
        const row = container.querySelector('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        const main = container.querySelector('.MarkdownNotebook__main') as HTMLElement
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement

        Object.defineProperty(canvas, 'getBoundingClientRect', {
            configurable: true,
            value: () => ({
                bottom: 100,
                height: 50,
                left: 0,
                right: 500,
                top: 50,
                width: 500,
                x: 0,
                y: 50,
                toJSON: () => ({}),
            }),
        })

        fireEvent.mouseDown(main, { button: 0, clientY: 140 })

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.textContent).toEqual('Thinking ...')
        expect(textBlocks).toHaveLength(1)
        expect(document.activeElement).toEqual(textBlocks[0])
        expect(window.getSelection()?.focusOffset).toEqual(0)
    })

    it('turns an Ask AI prompt back into regular text when backspacing at the start', () => {
        const onAskAI = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onAskAI }))
        const row = container.querySelector('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        selectTextInElement(editableTextBlock, 0, 0)
        fireEvent.keyDown(editableTextBlock, { key: 'Backspace' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')).toBeNull()
        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('Add a summary here')
    })

    it('adds heading blocks from slash menu h aliases', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const editableTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        editableTextBlock.textContent = '/'
        fireEvent.input(editableTextBlock)

        editableTextBlock.textContent = 'h1'
        fireEvent.input(editableTextBlock)

        const filteredInsertItems = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item'))
        expect(filteredInsertItems.map((item) => item.textContent)).toEqual(['Heading 1'])
        expect(filteredInsertItems[0].getAttribute('aria-selected')).toEqual('true')

        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        const heading = container.querySelector('h1.MarkdownNotebook__text-block')
        expect(heading).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(heading)
        expect(onChange).toHaveBeenLastCalledWith('#')
    })

    it('keeps newly inserted components active for keyboard row actions', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const row = container.querySelector('.MarkdownNotebook__row')

        expect(row).toBeInstanceOf(HTMLElement)
        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const funnelButton = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item')).find(
            (button) => button.textContent === 'Funnel'
        )

        expect(funnelButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(funnelButton as HTMLButtonElement)

        const shell = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement

        expect(shell).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(shell)
        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining('FunnelsQuery'))

        fireEvent.keyDown(shell, { key: 'Enter' })

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        expect(textBlocks).toHaveLength(1)
        expect(document.activeElement).toEqual(textBlocks[0])

        shell.focus()
        expect(document.activeElement).toEqual(shell)

        fireEvent.keyDown(shell, { key: 'Backspace' })

        expect(container.querySelector('.MarkdownNotebook__component-shell')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith('')
    })

    it('positions the slash menu as a fixed popover within the viewport', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: '' }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        Object.defineProperty(window, 'innerHeight', { configurable: true, value: 760 })
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 480 })
        Object.defineProperty(textBlock, 'getBoundingClientRect', {
            configurable: true,
            value: () => ({
                bottom: 728,
                height: 28,
                left: 420,
                right: 460,
                top: 700,
                width: 40,
                x: 420,
                y: 700,
                toJSON: () => ({}),
            }),
        })

        textBlock.textContent = '/'
        fireEvent.input(textBlock)

        const insertMenu = container.querySelector('.MarkdownNotebook__insert-menu') as HTMLElement

        expect(insertMenu).toBeInstanceOf(HTMLElement)
        expect(insertMenu.classList.contains('MarkdownNotebook__insert-menu--positioned')).toBe(true)
        expect(insertMenu.classList.contains('MarkdownNotebook__insert-menu--above')).toBe(true)
        expect(insertMenu.style.getPropertyValue('--markdown-notebook-insert-menu-left')).toEqual('84px')
        expect(insertMenu.style.getPropertyValue('--markdown-notebook-insert-menu-max-height')).toEqual('448px')
        expect(insertMenu.style.getPropertyValue('--markdown-notebook-insert-menu-top')).toEqual('688px')
        expect(insertMenu.style.getPropertyValue('--markdown-notebook-insert-menu-width')).toEqual('384px')
    })

    it('uses the boundary add button to insert a blank row before populated rows', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Intro paragraph', onChange }))
        const addBeforeButton = container.querySelector('.MarkdownNotebook__insert-boundary-button')

        expect(addBeforeButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(addBeforeButton as HTMLButtonElement)

        expect(onChange).toHaveBeenLastCalledWith(' \n\nIntro paragraph')
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()

        const insertedTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        insertedTextBlock.textContent = '/'
        fireEvent.input(insertedTextBlock)

        const trendButton = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item')).find(
            (button) => button.textContent === 'Trend'
        )

        expect(trendButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(trendButton as HTMLButtonElement)

        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining('/>\n\nIntro paragraph'))
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
        expect(toolbar?.classList.contains('MarkdownNotebook__format-toolbar--above')).toBe(true)

        act(() => {
            window.getSelection()?.removeAllRanges()
            document.dispatchEvent(new Event('selectionchange'))
        })

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeNull()
    })

    it('adds a link from the formatting toolbar', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'PostHog docs', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        selectTextNode(getFirstTextNode(textBlock), 0, 7, true)
        fireEvent.click(container.querySelector('button[aria-label="Link"]') as HTMLButtonElement)

        const linkInput = container.querySelector('input[aria-label="Link URL"]') as HTMLInputElement

        expect(linkInput).toBeInstanceOf(HTMLInputElement)
        fireEvent.change(linkInput, { target: { value: 'https://posthog.com/docs' } })
        fireEvent.keyDown(linkInput, { key: 'Enter' })

        expect(textBlock.querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(onChange).toHaveBeenLastCalledWith('[PostHog](https://posthog.com/docs) docs')
    })

    it('edits an existing link from the formatting toolbar', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: '[PostHog](https://posthog.com) docs', onChange })
        )
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        const linkedTextNode = textBlock.querySelector('a')?.firstChild

        expect(linkedTextNode).toBeInstanceOf(Text)

        selectTextNode(linkedTextNode as Text, 0, 7, true)
        fireEvent.click(container.querySelector('button[aria-label="Link"]') as HTMLButtonElement)

        const linkInput = container.querySelector('input[aria-label="Link URL"]') as HTMLInputElement

        expect(linkInput.value).toEqual('https://posthog.com')
        fireEvent.change(linkInput, { target: { value: 'https://posthog.com/docs' } })
        fireEvent.click(
            Array.from(container.querySelectorAll('.MarkdownNotebook__format-link-editor button')).find(
                (button) => button.textContent === 'Update'
            ) as HTMLButtonElement
        )

        expect(textBlock.querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(onChange).toHaveBeenLastCalledWith('[PostHog](https://posthog.com/docs) docs')
    })

    it('does not open the link editor for a collapsed selection inside an existing link', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: '[PostHog](https://posthog.com) docs' }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        const linkedTextNode = textBlock.querySelector('a')?.firstChild

        expect(linkedTextNode).toBeInstanceOf(Text)

        selectTextNode(linkedTextNode as Text, 3, 3, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeNull()
        expect(container.querySelector('input[aria-label="Link URL"]')).toBeNull()
        expect(document.activeElement).not.toBeInstanceOf(HTMLInputElement)
    })

    it('shows the formatting toolbar when selecting text on a line containing a link', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: '[PostHog](https://posthog.com) docs' }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        const textAfterLink = textBlock.lastChild

        expect(textAfterLink).toBeInstanceOf(Text)

        selectTextNode(textAfterLink as Text, 1, 5, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('input[aria-label="Link URL"]')).toBeNull()
    })

    it('keeps the formatting toolbar available after adding or removing a link on the row', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'PostHog docs' }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        selectTextNode(getFirstTextNode(textBlock), 0, 7, true)
        fireEvent.click(container.querySelector('button[aria-label="Link"]') as HTMLButtonElement)

        const linkInput = container.querySelector('input[aria-label="Link URL"]') as HTMLInputElement
        fireEvent.change(linkInput, { target: { value: 'https://posthog.com/docs' } })
        fireEvent.keyDown(linkInput, { key: 'Enter' })

        const textAfterLink = textBlock.lastChild
        expect(textAfterLink).toBeInstanceOf(Text)

        selectTextNode(textAfterLink as Text, 1, 5, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeInstanceOf(HTMLElement)

        selectTextNode(textBlock.querySelector('a')?.firstChild as Text, 0, 7, true)
        fireEvent.click(container.querySelector('button[aria-label="Link"]') as HTMLButtonElement)
        fireEvent.click(
            Array.from(container.querySelectorAll('.MarkdownNotebook__format-link-editor button')).find(
                (button) => button.textContent === 'Remove'
            ) as HTMLButtonElement
        )

        selectTextNode(getFirstTextNode(textBlock), 0, 7, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeInstanceOf(HTMLElement)
    })

    it('deletes selected text when pressing Enter and splits at the selection', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Hello selected text tail', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        selectTextInElement(textBlock, 6, 19)
        fireEvent.keyDown(textBlock, { key: 'Enter' })

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        expect(textBlocks.map((block) => block.textContent)).toEqual(['Hello ', ' tail'])
        expect(onChange).toHaveBeenLastCalledWith('Hello \n\n tail')
        expect(document.activeElement).toEqual(textBlocks[1])
    })

    it('deletes selected text with Backspace through notebook history', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Hello selected text tail', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        selectTextInElement(textBlock, 6, 19)
        fireEvent.keyDown(textBlock, { key: 'Backspace' })

        expect(textBlock.textContent).toEqual('Hello  tail')
        expect(onChange).toHaveBeenLastCalledWith('Hello  tail')

        fireEvent.keyDown(textBlock, { key: 'z', metaKey: true })

        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('Hello selected text tail')
        expect(onChange).toHaveBeenLastCalledWith('Hello selected text tail')
    })

    it('clears a focused row when all row text is selected and Backspace is pressed', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Delete me', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        textBlock.focus()
        selectElementContents(textBlock)
        fireEvent.keyDown(textBlock, { key: 'Backspace' })

        expect(textBlock.textContent).toEqual('')
        expect(document.activeElement).toEqual(textBlock)
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith('')
    })

    it('clears a row when the selection wraps the whole editable row element', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `Keep

Delete me

After`,
                onChange,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]

        textBlocks[1].focus()
        selectAroundElement(textBlocks[1])
        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        expect(textBlocks.map((block) => block.textContent)).toEqual(['Keep', '', 'After'])
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`Keep

 

After`)
    })

    it('merges a text row into the previous text row with Backspace and supports undo', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First row

Second row`,
                onChange,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]

        selectTextInElement(textBlocks[1], 0, 0)
        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        expect(container.querySelectorAll('[contenteditable="true"]')).toHaveLength(1)
        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('First rowSecond row')
        expect(onChange).toHaveBeenLastCalledWith('First rowSecond row')

        fireEvent.keyDown(container.querySelector('[contenteditable="true"]') as HTMLElement, {
            key: 'z',
            metaKey: true,
        })

        const restoredTextBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        expect(restoredTextBlocks.map((block) => block.textContent)).toEqual(['First row', 'Second row'])
        expect(onChange).toHaveBeenLastCalledWith(`First row

Second row`)
    })

    it('supports drag selection across text blocks', () => {
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const firstTextNode = textBlocks[0].firstChild
        const secondTextNode = textBlocks[1].firstChild

        expect(firstTextNode).toBeInstanceOf(Text)
        expect(secondTextNode).toBeInstanceOf(Text)

        const startRange = document.createRange()
        startRange.setStart(firstTextNode as Text, 2)
        startRange.collapse(true)
        const endRange = document.createRange()
        endRange.setStart(secondTextNode as Text, 4)
        endRange.collapse(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn((clientX: number) => (clientX === 10 ? startRange : endRange)),
        })

        fireEvent.mouseDown(textBlocks[0], { button: 0, clientX: 10, clientY: 10 })
        fireEvent.mouseMove(window.document, { clientX: 40, clientY: 40 })
        fireEvent.mouseUp(window.document)

        const selectedText = window.getSelection()?.toString() ?? ''
        expect(selectedText).toContain('rst paragraph')
        expect(selectedText).toContain('Seco')

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
    })

    it('lets native selection handle reversed drags within a text block', () => {
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph' }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        const textNode = textBlock.firstChild

        expect(textNode).toBeInstanceOf(Text)

        const rightRange = document.createRange()
        rightRange.setStart(textNode as Text, 10)
        rightRange.collapse(true)
        const leftRange = document.createRange()
        leftRange.setStart(textNode as Text, 2)
        leftRange.collapse(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn((clientX: number) => (clientX === 40 ? rightRange : leftRange)),
        })

        fireEvent.mouseDown(textBlock, { button: 0, clientX: 40, clientY: 10 })

        expect(fireEvent.mouseMove(window.document, { clientX: 10, clientY: 10 })).toBe(true)

        fireEvent.mouseUp(window.document)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
    })

    it('supports reversed drag selection across text blocks', () => {
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const firstTextNode = textBlocks[0].firstChild
        const secondTextNode = textBlocks[1].firstChild

        expect(firstTextNode).toBeInstanceOf(Text)
        expect(secondTextNode).toBeInstanceOf(Text)

        const firstRange = document.createRange()
        firstRange.setStart(firstTextNode as Text, 2)
        firstRange.collapse(true)
        const secondRange = document.createRange()
        secondRange.setStart(secondTextNode as Text, 4)
        secondRange.collapse(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn((_clientX: number, clientY: number) => (clientY === 40 ? secondRange : firstRange)),
        })

        fireEvent.mouseDown(textBlocks[1], { button: 0, clientX: 40, clientY: 40 })

        expect(fireEvent.mouseMove(window.document, { clientX: 10, clientY: 10 })).toBe(false)

        fireEvent.mouseUp(window.document)

        const selectedText = window.getSelection()?.toString() ?? ''
        expect(selectedText).toContain('rst paragraph')
        expect(selectedText).toContain('Seco')
        expect(window.getSelection()?.anchorNode).toEqual(secondTextNode)
        expect(window.getSelection()?.anchorOffset).toEqual(4)
        expect(window.getSelection()?.focusNode).toEqual(firstTextNode)
        expect(window.getSelection()?.focusOffset).toEqual(2)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
    })

    it('keeps upward drag selection when the caret range stays on the anchor row', () => {
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const originalElementFromPoint = document.elementFromPoint
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const secondTextNode = textBlocks[1].firstChild

        expect(secondTextNode).toBeInstanceOf(Text)

        const staleAnchorRange = document.createRange()
        staleAnchorRange.setStart(secondTextNode as Text, 4)
        staleAnchorRange.collapse(true)

        Object.defineProperty(textBlocks[0], 'getBoundingClientRect', {
            configurable: true,
            value: () => ({
                bottom: 24,
                height: 24,
                left: 0,
                right: 200,
                top: 0,
                width: 200,
                x: 0,
                y: 0,
                toJSON: () => ({}),
            }),
        })
        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn(() => staleAnchorRange),
        })
        Object.defineProperty(document, 'elementFromPoint', {
            configurable: true,
            value: jest.fn((_clientX: number, clientY: number) => (clientY === 40 ? textBlocks[1] : textBlocks[0])),
        })

        fireEvent.mouseDown(textBlocks[1], { button: 0, clientX: 40, clientY: 40 })

        expect(fireEvent.mouseMove(window.document, { clientX: 10, clientY: 4 })).toBe(false)

        fireEvent.mouseUp(window.document)

        const selectedText = window.getSelection()?.toString() ?? ''
        expect(selectedText).toContain('First paragraph')
        expect(selectedText).toContain('Seco')
        expect(textBlocks[0].getAttribute('contenteditable')).toEqual('false')
        expect(textBlocks[1].getAttribute('contenteditable')).toEqual('false')

        act(() => {
            window.getSelection()?.removeAllRanges()
            document.dispatchEvent(new Event('selectionchange'))
        })

        expect(textBlocks[0].getAttribute('contenteditable')).toEqual('true')
        expect(textBlocks[1].getAttribute('contenteditable')).toEqual('true')

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
        Object.defineProperty(document, 'elementFromPoint', {
            configurable: true,
            value: originalElementFromPoint,
        })
    })

    it('selects component blocks as active blocks when dragging upward across them', () => {
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Embed',
                label: 'Embed',
                category: 'Media',
                ViewComponent: () => createElement('div', { 'data-testid': 'component-output' }, 'Do not copy me'),
            },
        ])
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `Before paragraph

<Embed />

After paragraph`,
                registry,
            })
        )
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const component = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement
        const firstTextNode = textBlocks[0].firstChild
        const secondTextNode = textBlocks[1].firstChild

        expect(notebook).toBeInstanceOf(HTMLElement)
        expect(component).toBeInstanceOf(HTMLElement)
        expect(firstTextNode).toBeInstanceOf(Text)
        expect(secondTextNode).toBeInstanceOf(Text)

        const firstRange = document.createRange()
        firstRange.setStart(firstTextNode as Text, 3)
        firstRange.collapse(true)
        const secondRange = document.createRange()
        secondRange.setStart(secondTextNode as Text, 5)
        secondRange.collapse(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn((_clientX: number, clientY: number) => (clientY === 40 ? secondRange : firstRange)),
        })

        fireEvent.mouseDown(textBlocks[1], { button: 0, clientX: 40, clientY: 40 })
        fireEvent.mouseMove(window.document, { clientX: 10, clientY: 10 })
        fireEvent.mouseUp(window.document)

        const selectedText = window.getSelection()?.toString() ?? ''
        expect(selectedText).toContain('ore paragraph')
        expect(selectedText).toContain('After')
        expect(component.classList.contains('MarkdownNotebook__component-shell--selected')).toBe(true)

        const clipboardData = {
            setData: jest.fn(),
        }
        fireEvent.copy(notebook, { clipboardData })

        expect(clipboardData.setData).toHaveBeenCalledWith(
            'text/plain',
            `ore paragraph

<Embed />

After`
        )
        expect(clipboardData.setData).not.toHaveBeenCalledWith('text/plain', expect.stringContaining('Do not copy me'))

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
    })

    it('keeps text visible when changing a paragraph to a heading', () => {
        const { container, rerender } = render(createElement(MarkdownNotebook, { value: 'Selected heading text' }))

        expect(container.querySelector('p.MarkdownNotebook__text-block')?.textContent).toEqual('Selected heading text')

        rerender(createElement(MarkdownNotebook, { value: '# Selected heading text' }))

        expect(container.querySelector('h1.MarkdownNotebook__text-block')?.textContent).toEqual('Selected heading text')
    })

    it('copies selected notebook content as markdown including components', () => {
        const markdown = `Intro paragraph

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />

Closing paragraph`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const firstTextNode = textBlocks[0].firstChild
        const secondTextNode = textBlocks[1].firstChild

        expect(notebook).toBeInstanceOf(HTMLElement)
        expect(firstTextNode).toBeInstanceOf(Text)
        expect(secondTextNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(firstTextNode as Text, 6)
            range.setEnd(secondTextNode as Text, 7)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        const clipboardData = {
            setData: jest.fn(),
        }
        fireEvent.copy(notebook, { clipboardData })

        expect(clipboardData.setData).toHaveBeenCalledWith(
            'text/plain',
            `paragraph

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />

Closing`
        )
        expect(clipboardData.setData).toHaveBeenCalledWith(
            'text/markdown',
            `paragraph

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />

Closing`
        )
    })

    it('lets native copy handle text selected inside a focused component', () => {
        expect.hasAssertions()
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Embed',
                label: 'Embed',
                category: 'Media',
                ViewComponent: () => createElement('div', { 'data-testid': 'component-output' }, 'Copy this result'),
            },
        ])
        const { container } = render(createElement(MarkdownNotebook, { value: '<Embed />', registry }))
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const component = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement
        const output = container.querySelector('[data-testid="component-output"]') as HTMLElement
        const originalClipboard = navigator.clipboard
        const clipboard = {
            writeText: jest.fn(() => Promise.resolve()),
            readText: jest.fn(() => Promise.resolve('')),
        }

        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: clipboard,
        })

        try {
            component.focus()
            selectTextNode(getFirstTextNode(output), 5, 9)

            fireEvent.keyDown(component, { key: 'c', metaKey: true })

            expect(clipboard.writeText).not.toHaveBeenCalled()

            const clipboardData = {
                setData: jest.fn(),
            }
            fireEvent.copy(notebook, { clipboardData })

            expect(clipboardData.setData).not.toHaveBeenCalled()
        } finally {
            Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: originalClipboard,
            })
        }
    })

    it('copies and pastes a focused component as a cloned notebook block', async () => {
        expect.hasAssertions()
        const onChange = jest.fn()
        const markdown = `<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown, onChange }))
        const component = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement
        const originalClipboard = navigator.clipboard
        let clipboardText = ''
        const clipboard = {
            writeText: jest.fn((value: string) => {
                clipboardText = value
                return Promise.resolve()
            }),
            readText: jest.fn(() => Promise.resolve(clipboardText)),
        }

        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: clipboard,
        })

        try {
            component.focus()

            expect(document.activeElement).toEqual(component)

            fireEvent.keyDown(component, { key: 'c', metaKey: true })

            expect(clipboard.writeText).toHaveBeenCalledWith(markdown)

            fireEvent.keyDown(component, { key: 'v', metaKey: true })

            await waitFor(() => {
                if (container.querySelectorAll('.MarkdownNotebook__component-shell').length !== 2) {
                    throw new Error('Expected cloned component block to render')
                }
            })

            const components = Array.from(container.querySelectorAll('.MarkdownNotebook__component-shell'))

            expect(components).toHaveLength(2)
            expect(clipboard.readText).toHaveBeenCalled()
            expect(onChange).toHaveBeenLastCalledWith(`${markdown}\n\n${markdown}`)
            expect(document.activeElement).toEqual(components[1])
        } finally {
            Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: originalClipboard,
            })
        }
    })

    it('pastes markdown as notebook blocks', () => {
        const onChange = jest.fn()
        const pastedMarkdown = `# Pasted heading

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />

Tail with **bold** text`
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        fireEvent.paste(textBlock, {
            clipboardData: {
                getData: jest.fn((type: string) => (type === 'text/plain' ? pastedMarkdown : '')),
            },
        })

        expect(container.querySelector('h1.MarkdownNotebook__text-block')?.textContent).toEqual('Pasted heading')
        expect(container.querySelector('.MarkdownNotebook__component-shell')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('p.MarkdownNotebook__text-block')?.textContent).toEqual('Tail with bold text')
        expect(onChange).toHaveBeenLastCalledWith(pastedMarkdown)
    })

    it('pastes inline markdown into the active text block', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Hello ', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        const textNode = textBlock.firstChild

        expect(textNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(textNode as Text, 6)
            range.setEnd(textNode as Text, 6)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        fireEvent.paste(textBlock, {
            clipboardData: {
                getData: jest.fn((type: string) => (type === 'text/plain' ? '**bold**' : '')),
            },
        })

        expect(textBlock.textContent).toEqual('Hello bold')
        expect(onChange).toHaveBeenLastCalledWith('Hello **bold**')
    })

    it('undoes pasted markdown blocks as one notebook history step', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Intro paragraph', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        const textNode = textBlock.firstChild

        expect(textNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(textNode as Text, 15)
            range.setEnd(textNode as Text, 15)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        pastePlainText(
            textBlock,
            `# Pasted heading

Tail with **bold** text`
        )

        expect(onChange).toHaveBeenLastCalledWith(`Intro paragraph

# Pasted heading

Tail with **bold** text`)

        fireEvent.keyDown(textBlock, { key: 'z', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph')
        expect(container.querySelector('.MarkdownNotebook__component-shell')).toBeNull()
        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('Intro paragraph')
    })

    it('routes native contenteditable undo and redo through notebook history after paste', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Hello there', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        selectTextInElement(textBlock, 6, 6)
        pastePlainText(textBlock, '**bold** ')

        expect(onChange).toHaveBeenLastCalledWith('Hello **bold** there')
        expect(textBlock.textContent).toEqual('Hello bold there')

        fireHistoryBeforeInput(textBlock, 'historyUndo')

        expect(onChange).toHaveBeenLastCalledWith('Hello there')
        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('Hello there')

        fireHistoryBeforeInput(container.querySelector('[contenteditable="true"]') as HTMLElement, 'historyRedo')

        expect(onChange).toHaveBeenLastCalledWith('Hello **bold** there')
        expect(container.querySelector('[contenteditable="true"]')?.textContent).toEqual('Hello bold there')
    })

    it('pastes a URL over selected text as a link', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'PostHog docs', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        selectTextInElement(textBlock, 0, 7)
        pastePlainText(textBlock, 'https://posthog.com/docs')

        expect(textBlock.querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(textBlock.textContent).toEqual('PostHog docs')
        expect(onChange).toHaveBeenLastCalledWith('[PostHog](https://posthog.com/docs) docs')
    })

    it('pastes a URL over selected list item text as a link', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '- PostHog docs', onChange }))
        const listItem = container.querySelector('.MarkdownNotebook__list-item-content') as HTMLElement

        selectTextInElement(listItem, 0, 7)
        pastePlainText(listItem, 'https://posthog.com/docs')

        expect(listItem.querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(listItem.textContent).toEqual('PostHog docs')
        expect(onChange).toHaveBeenLastCalledWith('- [PostHog](https://posthog.com/docs) docs')
    })

    it('pastes a URL over selected table cell text as a link', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `| Name | Count |
| --- | --- |
| PostHog | 12 |`,
                onChange,
            })
        )
        const cells = Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content')) as HTMLElement[]

        selectTextInElement(cells[2], 0, 7)
        pastePlainText(cells[2], 'https://posthog.com/docs')

        expect(cells[2].querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(cells[2].textContent).toEqual('PostHog')
        expect(onChange).toHaveBeenLastCalledWith(`| Name | Count |
| --- | --- |
| [PostHog](https://posthog.com/docs) | 12 |`)
    })

    it('renders nested lists as editable list items', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `- Parent
  - Child
- Sibling`,
                onChange,
            })
        )
        const listBlock = container.querySelector('.MarkdownNotebook__list-block')
        const listItems = Array.from(
            container.querySelectorAll('.MarkdownNotebook__list-item-content')
        ) as HTMLElement[]

        expect(listBlock).toBeInstanceOf(HTMLElement)
        expect(listBlock?.querySelector('ul ul')).toBeInstanceOf(HTMLElement)
        expect(listItems).toHaveLength(3)
        expect(listItems.map((item) => item.textContent)).toEqual(['Parent', 'Child', 'Sibling'])
        expect(listItems[1].getAttribute('contenteditable')).toEqual('true')

        listItems[1].textContent = 'Updated child'
        fireEvent.input(listItems[1])

        expect(onChange).toHaveBeenLastCalledWith(`- Parent
  - Updated child
- Sibling`)
    })

    it('converts an ordered list shortcut at the start of a text row into a list', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        textBlock.textContent = '1.'
        fireEvent.input(textBlock)

        const listBlock = container.querySelector('.MarkdownNotebook__list-block')
        const listItem = container.querySelector('.MarkdownNotebook__list-item-content')

        expect(listBlock?.querySelector('ol')).toBeInstanceOf(HTMLElement)
        expect(listItem).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(listItem)
        expect(onChange).toHaveBeenLastCalledWith('1.')
    })

    it.each(['- ', '* ', '+ ', '• '])(
        'converts a bullet list shortcut "%s" at the start of a text row into a list',
        (shortcut) => {
            const onChange = jest.fn()
            const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
            const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

            textBlock.textContent = shortcut
            fireEvent.input(textBlock)

            const listBlock = container.querySelector('.MarkdownNotebook__list-block')
            const listItem = container.querySelector('.MarkdownNotebook__list-item-content')

            expect(listBlock?.querySelector('ul')).toBeInstanceOf(HTMLElement)
            expect(listItem).toBeInstanceOf(HTMLElement)
            expect(document.activeElement).toEqual(listItem)
            expect(onChange).toHaveBeenLastCalledWith('-')
        }
    )

    it('converts repeated heading shortcuts into heading levels up to h3', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))

        let textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        textBlock.textContent = '#'
        fireEvent.input(textBlock)

        expect(container.querySelector('h1.MarkdownNotebook__text-block')).toBeInstanceOf(HTMLElement)
        expect(onChange).toHaveBeenLastCalledWith('#')

        textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        textBlock.textContent = '#'
        fireEvent.input(textBlock)

        expect(container.querySelector('h2.MarkdownNotebook__text-block')).toBeInstanceOf(HTMLElement)
        expect(onChange).toHaveBeenLastCalledWith('##')

        textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement
        textBlock.textContent = '#'
        fireEvent.input(textBlock)

        expect(container.querySelector('h3.MarkdownNotebook__text-block')).toBeInstanceOf(HTMLElement)
        expect(onChange).toHaveBeenLastCalledWith('###')

        fireEvent.keyDown(container.querySelector('[contenteditable="true"]') as HTMLElement, { key: 'Backspace' })

        expect(container.querySelector('p.MarkdownNotebook__text-block')).toBeInstanceOf(HTMLElement)
        expect(onChange).toHaveBeenLastCalledWith('')
    })

    it('splits headings while preserving heading style except at the start', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '# HelloWorld', onChange }))
        let heading = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(heading, 5, 5)
        fireEvent.keyDown(heading, { key: 'Enter' })

        expect(
            Array.from(container.querySelectorAll('h1.MarkdownNotebook__text-block')).map((node) => node.textContent)
        ).toEqual(['Hello', 'World'])
        expect(onChange).toHaveBeenLastCalledWith(`# Hello

# World`)

        heading = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement
        selectTextInElement(heading, 0, 0)
        fireEvent.keyDown(heading, { key: 'Enter' })

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]

        expect(textBlocks[0].tagName).toEqual('P')
        expect(textBlocks[0].textContent).toEqual('')
        expect(textBlocks[1].tagName).toEqual('H1')
        expect(textBlocks[1].textContent).toEqual('Hello')
    })

    it('converts a blockquote shortcut at the start of a text row into a quote block', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        textBlock.textContent = '>'
        fireEvent.input(textBlock)

        const blockquote = container.querySelector('blockquote.MarkdownNotebook__text-block')

        expect(blockquote).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(blockquote)
        expect(onChange).toHaveBeenLastCalledWith('>')
    })

    it('indents list items with tab while preserving selection', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `- Parent
- Child`,
                onChange,
            })
        )
        const listItems = Array.from(
            container.querySelectorAll('.MarkdownNotebook__list-item-content')
        ) as HTMLElement[]
        const childTextNode = listItems[1].firstChild

        expect(childTextNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(childTextNode as Text, 3)
            range.setEnd(childTextNode as Text, 3)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        fireEvent.keyDown(listItems[1], { key: 'Tab' })

        expect(onChange).toHaveBeenLastCalledWith(`- Parent
  - Child`)
        expect(document.activeElement?.textContent).toEqual('Child')
        expect(window.getSelection()?.focusOffset).toEqual(3)
    })

    it('copies selected list items as markdown', () => {
        const markdown = `- Parent
  - Child
- Sibling`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const listItems = Array.from(
            container.querySelectorAll('.MarkdownNotebook__list-item-content')
        ) as HTMLElement[]
        const parentTextNode = listItems[0].firstChild
        const childTextNode = listItems[1].firstChild

        expect(parentTextNode).toBeInstanceOf(Text)
        expect(childTextNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(parentTextNode as Text, 2)
            range.setEnd(childTextNode as Text, 3)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        const clipboardData = {
            setData: jest.fn(),
        }
        fireEvent.copy(notebook, { clipboardData })

        expect(clipboardData.setData).toHaveBeenCalledWith(
            'text/plain',
            `- rent
  - Chi`
        )
    })

    it('renders and edits markdown tables', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `| Name | Count |
| --- | --- |
| Pageview | 12 |`,
                onChange,
            })
        )
        const table = container.querySelector('.MarkdownNotebook__table-block table')
        const cells = Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content')) as HTMLElement[]

        expect(table).toBeInstanceOf(HTMLTableElement)
        expect(table?.querySelectorAll('tr').length).toEqual(2)
        expect(table?.querySelector('.MarkdownNotebook__table-structure-control')).toBeNull()
        expect(container.querySelector('.MarkdownNotebook__table-structure-overlay')).toBeInstanceOf(HTMLElement)
        expect(cells.map((cell) => cell.textContent)).toEqual(['Name', 'Count', 'Pageview', '12'])
        expect(cells[0].getAttribute('contenteditable')).toEqual('true')

        cells[2].textContent = 'Signup'
        fireEvent.input(cells[2])

        expect(onChange).toHaveBeenLastCalledWith(`| Name | Count |
| --- | --- |
| Signup | 12 |`)
    })

    it('renders single-column markdown tables', () => {
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `| Column 1 |
| --- |
| ewfwef |
| efaew |`,
            })
        )
        const table = container.querySelector('.MarkdownNotebook__table-block table')
        const cells = Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content')) as HTMLElement[]

        expect(table).toBeInstanceOf(HTMLTableElement)
        expect(cells.map((cell) => cell.textContent)).toEqual(['Column 1', 'ewfwef', 'efaew'])
        expect(container.querySelector('p.MarkdownNotebook__text-block')).toBeNull()
    })

    it('moves between table cells with tab and adds rows with enter', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `| Name | Count |
| --- | --- |
| Pageview | 12 |`,
                onChange,
            })
        )
        const getCells = (): HTMLElement[] =>
            Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content')) as HTMLElement[]

        fireEvent.keyDown(getCells()[0], { key: 'Tab' })

        expect(document.activeElement).toEqual(getCells()[1])

        fireEvent.keyDown(getCells()[2], { key: 'Enter' })

        expect(onChange).toHaveBeenLastCalledWith(`| Name | Count |
| --- | --- |
| Pageview | 12 |
|  |  |`)
        expect(document.activeElement).toEqual(getCells()[4])
    })

    it('adds and removes table rows and columns with controls', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `| Name | Count |
| --- | --- |
| Pageview | 12 |`,
                onChange,
            })
        )
        const getButton = (label: string): HTMLButtonElement => {
            const button = container.querySelector(`button[aria-label="${label}"]`)
            expect(button).toBeInstanceOf(HTMLButtonElement)
            return button as HTMLButtonElement
        }

        fireEvent.click(getButton('Add column after column 2'))

        expect(onChange).toHaveBeenLastCalledWith(`| Name | Count |  |
| --- | --- | --- |
| Pageview | 12 |  |`)
        expect(document.activeElement).toEqual(
            Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content'))[2]
        )

        fireEvent.click(getButton('Remove column 3'))

        expect(onChange).toHaveBeenLastCalledWith(`| Name | Count |
| --- | --- |
| Pageview | 12 |`)

        fireEvent.click(getButton('Add row after row 1'))

        expect(onChange).toHaveBeenLastCalledWith(`| Name | Count |
| --- | --- |
| Pageview | 12 |
|  |  |`)

        fireEvent.click(getButton('Remove row 2'))

        expect(onChange).toHaveBeenLastCalledWith(`| Name | Count |
| --- | --- |
| Pageview | 12 |`)
    })

    it('pastes markdown tables as notebook table blocks', () => {
        const onChange = jest.fn()
        const pastedMarkdown = `| Name | Count |
| --- | ---: |
| Pageview | **12** |`
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        fireEvent.paste(textBlock, {
            clipboardData: {
                getData: jest.fn((type: string) => (type === 'text/plain' ? pastedMarkdown : '')),
            },
        })

        expect(container.querySelector('.MarkdownNotebook__table-block')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__table-cell-content')?.textContent).toEqual('Name')
        expect(onChange).toHaveBeenLastCalledWith(pastedMarkdown)
    })

    it('copies selected tables as markdown', () => {
        const markdown = `| Name | Count |
| --- | --- |
| Pageview | 12 |`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const cells = Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content')) as HTMLElement[]
        const firstTextNode = cells[0].firstChild
        const lastTextNode = cells[3].firstChild

        expect(firstTextNode).toBeInstanceOf(Text)
        expect(lastTextNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(firstTextNode as Text, 0)
            range.setEnd(lastTextNode as Text, 2)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        const clipboardData = {
            setData: jest.fn(),
        }
        fireEvent.copy(notebook, { clipboardData })

        expect(clipboardData.setData).toHaveBeenCalledWith('text/plain', markdown)
    })

    it('moves the formatting toolbar below selections at the top of the viewport', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'Select this text' }))
        const textBlock = container.querySelector('[contenteditable="true"]')

        expect(textBlock).toBeInstanceOf(HTMLElement)
        const editableTextBlock = textBlock as HTMLElement
        editableTextBlock.style.lineHeight = '20px'
        const selectedTextNode = editableTextBlock.firstChild

        expect(selectedTextNode).toBeInstanceOf(Text)

        const selectionRect = {
            bottom: 24,
            height: 20,
            left: 100,
            right: 180,
            top: 4,
            width: 80,
            x: 100,
            y: 4,
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
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-top')).toEqual(
            '44px'
        )
        expect(toolbar?.classList.contains('MarkdownNotebook__format-toolbar--below')).toBe(true)
    })

    it('adds an editable blank row after a terminal component', () => {
        const onChange = jest.fn()
        const markdown = `<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown, onChange }))
        const trailingTextBlock = container.querySelector('[contenteditable="true"]')

        expect(trailingTextBlock).toBeInstanceOf(HTMLElement)

        const editableTrailingBlock = trailingTextBlock as HTMLElement
        editableTrailingBlock.focus()
        editableTrailingBlock.textContent = 'Follow-up note'
        fireEvent.input(editableTrailingBlock)

        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining('/>\n\nFollow-up note'))
    })

    it('creates a trailing blank row when clicking blank space below a notebook ending in text', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
                onChange,
            })
        )
        const main = container.querySelector('.MarkdownNotebook__main')
        const canvas = container.querySelector('.MarkdownNotebook__canvas')

        expect(main).toBeInstanceOf(HTMLElement)
        expect(canvas).toBeInstanceOf(HTMLElement)

        Object.defineProperty(canvas, 'getBoundingClientRect', {
            value: () => ({
                bottom: 200,
                height: 100,
                left: 0,
                right: 500,
                top: 100,
                width: 500,
                x: 0,
                y: 100,
                toJSON: () => ({}),
            }),
        })

        fireEvent.mouseDown(main as HTMLElement, { button: 0, clientY: 260 })

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        expect(onChange).toHaveBeenLastCalledWith(`First paragraph

Second paragraph

 `)
        expect(textBlocks).toHaveLength(3)
        expect(document.activeElement).toEqual(textBlocks[2])
        expect(window.getSelection()?.focusOffset).toEqual(0)
    })

    it('combines text blocks when pressing backspace at the start of a text block', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
                onChange,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]

        selectTextInElement(textBlocks[1], 0, 0)
        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        expect(onChange).toHaveBeenLastCalledWith('First paragraphSecond paragraph')
        expect(container.querySelectorAll('[contenteditable="true"]')).toHaveLength(1)
        expect(document.activeElement?.textContent).toEqual('First paragraphSecond paragraph')
        expect(window.getSelection()?.focusOffset).toEqual('First paragraph'.length)
    })

    it('deletes an empty text row and moves the cursor to the previous text block on backspace', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph', onChange }))
        const firstTextBlock = container.querySelector('[contenteditable="true"]') as HTMLElement

        selectTextInElement(firstTextBlock, 'First paragraph'.length, 'First paragraph'.length)
        fireEvent.keyDown(firstTextBlock, { key: 'Enter' })

        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]

        expect(textBlocks).toHaveLength(2)
        expect(document.activeElement).toEqual(textBlocks[1])

        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        expect(onChange).toHaveBeenLastCalledWith('First paragraph')
        expect(container.querySelectorAll('[contenteditable="true"]')).toHaveLength(1)
        expect(document.activeElement?.textContent).toEqual('First paragraph')
        expect(window.getSelection()?.focusOffset).toEqual('First paragraph'.length)
    })

    it('moves focus between notebook rows with arrow keys while retaining cursor offset', () => {
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />

After component`,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const componentShell = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement
        const firstTextNode = textBlocks[0].firstChild
        const secondTextNode = textBlocks[1].firstChild

        expect(textBlocks).toHaveLength(3)
        expect(componentShell).toBeInstanceOf(HTMLElement)
        expect(firstTextNode).toBeInstanceOf(Text)
        expect(secondTextNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(firstTextNode as Text, 5)
            range.setEnd(firstTextNode as Text, 5)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        fireEvent.keyDown(textBlocks[0], { key: 'ArrowDown' })

        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(5)

        fireEvent.keyDown(textBlocks[1], { key: 'ArrowUp' })

        expect(document.activeElement).toEqual(textBlocks[0])
        expect(window.getSelection()?.focusOffset).toEqual(5)

        act(() => {
            const range = document.createRange()
            range.setStart(secondTextNode as Text, 5)
            range.setEnd(secondTextNode as Text, 5)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })

        fireEvent.keyDown(textBlocks[1], { key: 'ArrowDown' })

        expect(document.activeElement).toEqual(componentShell)

        fireEvent.keyDown(componentShell, { key: 'ArrowUp' })

        expect(document.activeElement).toEqual(textBlocks[1])

        componentShell.focus()
        fireEvent.keyDown(componentShell, { key: 'ArrowDown' })

        expect(document.activeElement).toEqual(textBlocks[2])
    })

    it('toggles component edit and view panels independently with edit above view', () => {
        const markdown = `<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const shell = container.querySelector('.MarkdownNotebook__component-shell')
        const modeButtons = Array.from(
            container.querySelectorAll('.MarkdownNotebook__component-mode-actions button')
        ) as HTMLButtonElement[]
        const toolbarLeftChildren = Array.from(
            container.querySelector('.MarkdownNotebook__component-toolbar-left')?.children ?? []
        )
        const deleteButton = container.querySelector('button[aria-label="Delete component"]')

        expect(shell).toBeInstanceOf(HTMLElement)
        expect(modeButtons).toHaveLength(2)
        expect(toolbarLeftChildren[0].classList.contains('MarkdownNotebook__component-title')).toBe(true)
        expect(toolbarLeftChildren[1].classList.contains('MarkdownNotebook__component-mode-actions')).toBe(true)
        expect(deleteButton).toBeInstanceOf(HTMLButtonElement)
        expect(container.querySelector('.MarkdownNotebook__component-preview')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__component-edit')).toBeNull()

        fireEvent.click(modeButtons[0])

        const stackedPanels = Array.from(shell?.querySelectorAll('.MarkdownNotebook__component-panel') ?? [])
        expect(stackedPanels).toHaveLength(2)
        expect(stackedPanels[0].querySelector('.MarkdownNotebook__component-edit')).toBeInstanceOf(HTMLElement)
        expect(stackedPanels[1].querySelector('.MarkdownNotebook__component-preview')).toBeInstanceOf(HTMLElement)

        fireEvent.click(modeButtons[1])

        expect(container.querySelector('.MarkdownNotebook__component-preview')).toBeNull()
        expect(container.querySelector('.MarkdownNotebook__component-edit')).toBeInstanceOf(HTMLElement)
    })

    it('opens both panels for component blocks inserted through a value update', () => {
        const { container, rerender } = render(createElement(MarkdownNotebook, { value: 'Intro paragraph' }))

        rerender(
            createElement(MarkdownNotebook, {
                value: `Intro paragraph

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />`,
            })
        )

        const shell = container.querySelector('.MarkdownNotebook__component-shell')
        const stackedPanels = Array.from(shell?.querySelectorAll('.MarkdownNotebook__component-panel') ?? [])

        expect(stackedPanels).toHaveLength(2)
        expect(stackedPanels[0].querySelector('.MarkdownNotebook__component-edit')).toBeInstanceOf(HTMLElement)
        expect(stackedPanels[1].querySelector('.MarkdownNotebook__component-preview')).toBeInstanceOf(HTMLElement)
    })

    it('shows SQL component titles as colored tags with icons', () => {
        const markdown = `<Query query={{"kind":"DataTableNode","source":{"kind":"HogQLQuery","query":"select event from events"}}} />`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const title = container.querySelector('.MarkdownNotebook__component-title')

        expect(title).toBeInstanceOf(HTMLElement)
        expect(title?.textContent).toEqual('SQL')
        expect(title?.classList.contains('MarkdownNotebook__component-title--sql')).toBe(true)
        expect(title?.querySelector('.MarkdownNotebook__component-title-icon')).toBeInstanceOf(HTMLElement)
    })

    it('does not duplicate component titles inside view content', () => {
        const markdown = `<DuckSQL title="SQL (DuckDB)" code="select * from events" returnVariable="duck_df" />`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const shell = container.querySelector('.MarkdownNotebook__component-shell')

        expect(shell).toBeInstanceOf(HTMLElement)
        expect(shell?.querySelector('.MarkdownNotebook__component-title')?.textContent).toEqual('SQL (DuckDB)')
        expect(shell?.querySelector('.MarkdownNotebook__component-preview-header')).toBeNull()
        expect(shell?.querySelector('.MarkdownNotebook__component-badge')).toBeNull()
        expect(shell?.textContent?.match(/SQL \(DuckDB\)/g)).toHaveLength(1)
        expect(shell?.textContent).toContain('select * from events')
    })
})
