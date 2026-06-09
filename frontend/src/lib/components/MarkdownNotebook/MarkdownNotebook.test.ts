import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

const NOTEBOOK_TEST_EDITABLE_SELECTOR =
    '.MarkdownNotebook__text-block[contenteditable="true"], .MarkdownNotebook__list-item-content[contenteditable="true"], .MarkdownNotebook__table-cell-content[contenteditable="true"]'
const TEST_NOTEBOOK_TITLE = 'Notebook title'
const TEST_NOTEBOOK_TITLE_MARKDOWN = `# ${TEST_NOTEBOOK_TITLE}`

function withNotebookTitle(markdown: string): string {
    return markdown ? `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n${markdown}` : TEST_NOTEBOOK_TITLE_MARKDOWN
}

function getEditableTextBlocks(container: HTMLElement): HTMLElement[] {
    return Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
}

function getBodyTextBlock(container: HTMLElement, bodyIndex = 0): HTMLElement {
    const textBlock = getEditableTextBlocks(container)[bodyIndex + 1]

    expect(textBlock).toBeInstanceOf(HTMLElement)

    return textBlock
}

function getFormattingStyleButton(container: HTMLElement): HTMLButtonElement {
    const button = container.querySelector('.MarkdownNotebook__format-style-button')

    expect(button).toBeInstanceOf(HTMLButtonElement)

    return button as HTMLButtonElement
}

async function waitForFormattingStyleMenuItem(label: string): Promise<HTMLElement> {
    return await waitFor(() => screen.getByRole('menuitem', { name: label }))
}

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

function selectTextNodeWithRect(textNode: Text, start: number, end: number, rect: DOMRect): void {
    act(() => {
        const range = document.createRange()
        range.setStart(textNode, start)
        range.setEnd(textNode, end)
        Object.defineProperty(range, 'getBoundingClientRect', { value: () => rect })
        Object.defineProperty(range, 'getClientRects', { value: () => [rect] })
        const selection = window.getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
        document.dispatchEvent(new Event('selectionchange'))
    })
}

function selectTextAcrossNodes(
    startTextNode: Text,
    start: number,
    endTextNode: Text,
    end: number,
    showToolbar = false
): void {
    act(() => {
        const range = document.createRange()
        range.setStart(startTextNode, start)
        range.setEnd(endTextNode, end)
        if (showToolbar) {
            const selectionRect = {
                bottom: 160,
                height: 60,
                left: 100,
                right: 260,
                top: 100,
                width: 160,
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

function fireBeforeInput(element: HTMLElement, inputType: string): void {
    const event = new Event('beforeinput', { bubbles: true, cancelable: true }) as InputEvent
    Object.defineProperty(event, 'inputType', { value: inputType })
    fireEvent(element, event)
}

function fireHistoryBeforeInput(element: HTMLElement, inputType: 'historyUndo' | 'historyRedo'): void {
    fireBeforeInput(element, inputType)
}

function createTouchList(touches: Touch[]): TouchList {
    const touchList = touches as unknown as TouchList & { item: (index: number) => Touch | null }
    touchList.item = (index: number): Touch | null => touches[index] ?? null
    return touchList
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

    it.each([
        ['LF', '\n'],
        ['CRLF', '\r\n'],
        ['CR', '\r'],
    ])('normalizes %s linebreaks across paragraphs, quotes, and lists', (_, lineBreak) => {
        const markdown = [
            'First line',
            'continued line',
            '',
            '> Quote one',
            '> Quote two',
            '',
            '- Parent',
            '  - Child',
        ].join(lineBreak)

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(`First line
continued line

> Quote one
> Quote two

- Parent
  - Child`)
    })

    it('normalizes mixed linebreaks in one markdown document', () => {
        const markdown = 'First line\r\ncontinued line\r\r\n> Quote one\r> Quote two\n\n1. Parent\r\n   1. Child'

        expect(serializeMarkdownNotebook(parseMarkdownNotebook(markdown))).toEqual(`First line
continued line

> Quote one
> Quote two

1. Parent
  1. Child`)
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

    it('deduplicates reconciled node ids for repeated markdown blocks', () => {
        const previous = parseMarkdownNotebook('Different block')
        const next = parseMarkdownNotebook(`Repeated block

Repeated block`)
        next.nodes[1].id = next.nodes[0].id

        const reconciled = reconcileNotebookDocuments(previous, next)
        const nodeIds = reconciled.document.nodes.map((node) => node.id)

        expect(new Set(nodeIds).size).toEqual(nodeIds.length)
    })

    it('sanitizes edited HTML into supported inline nodes', () => {
        const element = document.createElement('div')
        element.innerHTML = 'Hello <strong>bold</strong> <script>alert(1)</script><u>underlined</u>'

        expect(serializeInlineNodes(htmlElementToInlineNodes(element))).toEqual(
            'Hello **bold** alert(1)<u>underlined</u>'
        )
    })

    it('converts browser block wrappers into hard breaks', () => {
        const element = document.createElement('div')
        element.innerHTML = 'First<div>Second</div><p>Third</p>'

        expect(serializeInlineNodes(htmlElementToInlineNodes(element))).toEqual(`First
Second
Third
`)
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

    it('normalizes the first rendered row into a notebook title', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: `Notebook name\n\nBody line`, onChange }))
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement
        const body = container.querySelector('p.MarkdownNotebook__text-block') as HTMLElement

        expect(title).toBeInstanceOf(HTMLElement)
        expect(title.textContent).toEqual('Notebook name')
        expect(body.textContent).toEqual('Body line')

        title.textContent = 'Updated name'
        fireEvent.input(title)

        expect(onChange).toHaveBeenLastCalledWith(`# Updated name\n\nBody line`)
    })

    it('copies the selected notebook title with heading markdown', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle('Body line') }))
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement
        const clipboardData = {
            setData: jest.fn(),
        }

        selectTextInElement(title, 0, TEST_NOTEBOOK_TITLE.length)
        fireEvent.copy(notebook, { clipboardData })

        expect(clipboardData.setData).toHaveBeenCalledWith('text/plain', TEST_NOTEBOOK_TITLE_MARKDOWN)
        expect(clipboardData.setData).toHaveBeenCalledWith('text/markdown', TEST_NOTEBOOK_TITLE_MARKDOWN)
    })

    it('splits the notebook title into the first body line when pressing enter', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '# NotebookTitle', onChange }))
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(title, 'Notebook'.length, 'Notebook'.length)
        fireEvent.keyDown(title, { key: 'Enter' })

        const textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['Notebook', 'Title'])
        expect(textBlocks[0].tagName).toEqual('H1')
        expect(textBlocks[1].tagName).toEqual('P')
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(onChange).toHaveBeenLastCalledWith(`# Notebook\n\nTitle`)
    })

    it('splits the notebook title from root-targeted enter events', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '# NotebookTitle', onChange }))
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(title, 0, 0)
        fireEvent.keyDown(canvas, { key: 'Enter' })

        const textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.tagName)).toEqual(['H1', 'P'])
        expect(textBlocks.map((block) => block.textContent)).toEqual(['', 'NotebookTitle'])
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(onChange).toHaveBeenLastCalledWith(`# \n\nNotebookTitle`)
    })

    it('splits the notebook title from native insertParagraph events', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '# NotebookTitle', onChange }))
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(title, 0, 0)
        act(() => {
            canvas.dispatchEvent(
                new InputEvent('beforeinput', { bubbles: true, cancelable: true, inputType: 'insertParagraph' })
            )
        })

        let textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.tagName)).toEqual(['H1', 'P'])
        expect(textBlocks.map((block) => block.textContent)).toEqual(['', 'NotebookTitle'])

        textBlocks[0].textContent = 'New title'
        fireEvent.input(textBlocks[0])

        textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.tagName)).toEqual(['H1', 'P'])
        expect(textBlocks.map((block) => block.textContent)).toEqual(['New title', 'NotebookTitle'])
        expect(onChange).toHaveBeenLastCalledWith(`# New title\n\nNotebookTitle`)
    })

    it('merges the notebook title split back together when backspacing after Enter', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `# title

line of text

another line`,
                onChange,
            })
        )
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(title, 'ti'.length, 'ti'.length)
        fireEvent.keyDown(title, { key: 'Enter' })

        let textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['ti', 'tle', 'line of text', 'another line'])
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)

        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['title', 'line of text', 'another line'])
        expect(document.activeElement).toEqual(textBlocks[0])
        expect(window.getSelection()?.focusOffset).toEqual('ti'.length)
        expect(onChange).toHaveBeenLastCalledWith(`# title

line of text

another line`)
    })

    it('splits the notebook title again after merging an Enter split with Backspace', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `# title

line of text

another line`,
                onChange,
            })
        )
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(title, 'ti'.length, 'ti'.length)
        fireEvent.keyDown(title, { key: 'Enter' })

        let textBlocks = getEditableTextBlocks(container)
        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        textBlocks = getEditableTextBlocks(container)
        fireEvent.keyDown(textBlocks[0], { key: 'Enter' })

        textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['ti', 'tle', 'line of text', 'another line'])
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`# ti

tle

line of text

another line`)
    })

    it('splits the notebook title again after native Enter Backspace Enter input events', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `# title

line of text

another line`,
                onChange,
            })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(title, 'ti'.length, 'ti'.length)
        fireBeforeInput(canvas, 'insertParagraph')

        let textBlocks = getEditableTextBlocks(container)
        fireBeforeInput(canvas, 'deleteContentBackward')

        textBlocks = getEditableTextBlocks(container)
        fireBeforeInput(canvas, 'insertParagraph')

        textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['ti', 'tle', 'line of text', 'another line'])
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`# ti

tle

line of text

another line`)
    })

    it('merges the notebook title split back together after native insertParagraph', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `# title

line of text

another line`,
                onChange,
            })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(title, 'ti'.length, 'ti'.length)
        act(() => {
            canvas.dispatchEvent(
                new InputEvent('beforeinput', { bubbles: true, cancelable: true, inputType: 'insertParagraph' })
            )
        })

        let textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['ti', 'tle', 'line of text', 'another line'])
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)

        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['title', 'line of text', 'another line'])
        expect(document.activeElement).toEqual(textBlocks[0])
        expect(window.getSelection()?.focusOffset).toEqual('ti'.length)
        expect(onChange).toHaveBeenLastCalledWith(`# title

line of text

another line`)
    })

    it('keeps only the first pasted line in the notebook title', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '# Old title', onChange }))
        const title = container.querySelector('h1.MarkdownNotebook__text-block') as HTMLElement

        selectElementContents(title)
        pastePlainText(
            title,
            `New title
Body line
## Body heading`
        )

        const textBlocks = getEditableTextBlocks(container)
        expect(textBlocks.map((block) => block.textContent)).toEqual(['New title', 'Body line', 'Body heading'])
        expect(textBlocks.map((block) => block.tagName)).toEqual(['H1', 'P', 'P'])
        expect(onChange).toHaveBeenLastCalledWith(`# New title\n\nBody line\n\nBody heading`)
    })

    it('keeps repeated text rows independent while editing', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`Repeated block

Repeated block

Repeated block`),
                onChange,
            })
        )
        const firstRepeatedBlock = getBodyTextBlock(container, 0)
        const secondRepeatedBlock = getBodyTextBlock(container, 1)
        const thirdRepeatedBlock = getBodyTextBlock(container, 2)
        const nodeIds = [firstRepeatedBlock, secondRepeatedBlock, thirdRepeatedBlock].map(
            (block) => block.dataset.markdownNotebookNodeId
        )

        expect(new Set(nodeIds).size).toEqual(nodeIds.length)

        secondRepeatedBlock.textContent = 'Changed block'
        fireEvent.input(secondRepeatedBlock)

        expect([firstRepeatedBlock, secondRepeatedBlock, thirdRepeatedBlock].map((block) => block.textContent)).toEqual(
            ['Repeated block', 'Changed block', 'Repeated block']
        )
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nRepeated block\n\nChanged block\n\nRepeated block`
        )
    })

    it('keeps rapid text input stable while the editable DOM owns the active keystrokes', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)

        expect(textBlock).toBeInstanceOf(HTMLElement)
        const editableTextBlock = textBlock as HTMLElement

        const typedValues = ['h', 'he', 'her', 'here', 'here is', 'here is another', 'here is another one']

        editableTextBlock.focus()
        typedValues.forEach((typedValue) => {
            editableTextBlock.textContent = typedValue
            fireEvent.input(editableTextBlock)
        })

        expect(onChange).toHaveBeenLastCalledWith('# here is another one')
        expect(editableTextBlock.textContent).toEqual('here is another one')
    })

    it('undoes and redoes notebook text edits with keyboard shortcuts', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: '', onChange }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)

        expect(textBlock).toBeInstanceOf(HTMLElement)
        const editableTextBlock = textBlock as HTMLElement

        editableTextBlock.focus()
        editableTextBlock.textContent = 'hello'
        fireEvent.input(editableTextBlock)
        editableTextBlock.textContent = 'hello world'
        fireEvent.input(editableTextBlock)

        fireEvent.keyDown(editableTextBlock, { key: 'z', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith('# hello')
        expect(editableTextBlock.textContent).toEqual('hello')
        expect(document.activeElement).toEqual(editableTextBlock)

        fireEvent.keyDown(editableTextBlock, { key: 'z', metaKey: true, shiftKey: true })

        expect(onChange).toHaveBeenLastCalledWith('# hello world')
        expect(editableTextBlock.textContent).toEqual('hello world')

        fireEvent.keyDown(editableTextBlock, { key: 'z', ctrlKey: true })

        expect(onChange).toHaveBeenLastCalledWith('# hello')
        expect(editableTextBlock.textContent).toEqual('hello')

        fireEvent.keyDown(editableTextBlock, { key: 'y', ctrlKey: true })

        expect(onChange).toHaveBeenLastCalledWith('# hello world')
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
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(' '),
                remoteValue: withNotebookTitle(' '),
                onChange,
                registry,
            })
        )
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const editableTextBlock = getBodyTextBlock(container)
        editableTextBlock.textContent = 'iframe'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        const savedMarkdown = onChange.mock.calls[onChange.mock.calls.length - 1][0]
        expect(savedMarkdown).toEqual(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n<Embed src="https://posthog.com" title="PostHog" />`
        )

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
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange, onInteractionStateChange })
        )
        const editableTextBlock = getBodyTextBlock(container)

        editableTextBlock.textContent = '/'
        fireEvent.input(editableTextBlock)

        const firstActiveInteractionCall = onInteractionStateChange.mock.calls.findIndex(([isActive]) => isActive)

        expect(firstActiveInteractionCall).toBeGreaterThanOrEqual(0)
        expect(onChange).toHaveBeenCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n `)
        expect(onInteractionStateChange.mock.invocationCallOrder[firstActiveInteractionCall]).toBeLessThan(
            onChange.mock.invocationCallOrder[0]
        )
    })

    it('only shows the writing placeholder for an empty notebook', () => {
        const { container: emptyContainer } = render(createElement(MarkdownNotebook, { value: '' }))

        expect(emptyContainer.querySelectorAll('[data-placeholder="Untitled notebook"]')).toHaveLength(1)
        expect(emptyContainer.querySelectorAll('[data-placeholder="Start writing..."]')).toHaveLength(0)

        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)

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
        expect(debugTextarea.value).toEqual('# First paragraph')

        const editableTextBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
        editableTextBlock.textContent = 'Updated paragraph'
        fireEvent.input(editableTextBlock)

        expect(debugTextarea.value).toEqual('# Updated paragraph')

        fireEvent.change(debugTextarea, { target: { value: '# Edited from debug' } })

        expect(debugTextarea.value).toEqual('# Edited from debug')
        expect(container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)?.textContent).toEqual('Edited from debug')

        const closeButton = Array.from(container.querySelectorAll('.MarkdownNotebook__debug-drawer button')).find(
            (button) => button.textContent?.includes('Close')
        )
        expect(closeButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(closeButton as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__debug-drawer')).toBeNull()
    })

    it('uses the boundary add button to insert a blank row after populated rows', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Intro paragraph'), onChange })
        )
        const boundaryButtons = Array.from(
            container.querySelectorAll('.MarkdownNotebook__insert-boundary-button')
        ) as HTMLButtonElement[]
        const addAfterButton = boundaryButtons[1]

        expect(boundaryButtons).toHaveLength(2)
        fireEvent.click(addAfterButton)

        expect(container.querySelector('.MarkdownNotebook__row--insert-menu-open')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph\n\n `)
        const textBlocks = getEditableTextBlocks(container)
        const slashTextBlock = textBlocks[2]
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
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph\n\nzzzz`)

        expect(container.querySelector('.MarkdownNotebook__empty-menu')?.textContent).toEqual('No components found')

        fireEvent.keyDown(slashTextBlock, { key: 'Enter' })
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph\n\n `)
        expect(document.activeElement).toEqual(slashTextBlock)
        expect(slashTextBlock.textContent).toEqual('')

        slashTextBlock.textContent = 'tr'
        fireEvent.input(slashTextBlock)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph\n\ntr`)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)

        const filteredInsertItems = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item'))
        expect(filteredInsertItems[0].textContent).toEqual('Trend')
        expect(filteredInsertItems[0].getAttribute('aria-selected')).toEqual('true')

        const trendButton = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item')).find(
            (button) => button.textContent === 'Trend'
        )

        expect(trendButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(trendButton as HTMLButtonElement)

        expect(onChange).toHaveBeenLastCalledWith(
            expect.stringContaining(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph\n\n<Query`)
        )
        expect(container.querySelector('.MarkdownNotebook__component-edit')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__component-preview')).toBeInstanceOf(HTMLElement)
    })

    it('keeps inserted blank rows after receiving the serialized markdown value', () => {
        const onChange = jest.fn()
        const { container, rerender } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Intro paragraph'), onChange })
        )
        const addAfterButton = Array.from(
            container.querySelectorAll('.MarkdownNotebook__insert-boundary-button')
        )[1] as HTMLButtonElement

        fireEvent.click(addAfterButton)

        const nextValue = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as string
        rerender(createElement(MarkdownNotebook, { value: nextValue, onChange }))

        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
        expect(nextValue).toEqual(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph\n\n `)
        expect(textBlocks).toHaveLength(3)
        expect(textBlocks[2].textContent).toEqual('')
    })

    it('adds and focuses a trailing blank row when clicking below the notebook canvas', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Intro paragraph'), onChange })
        )
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

        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph\n\n `)
        expect(textBlocks).toHaveLength(3)
        expect(document.activeElement).toEqual(textBlocks[2])
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
        expect(boundaryButtons).toHaveLength(2)
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
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
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

        const boundaryHoverZones = Array.from(
            container.querySelectorAll('.MarkdownNotebook__insert-boundary-hover-zone')
        )
        expect(boundaryHoverZones).toHaveLength(4)

        fireEvent.mouseEnter(boundaryHoverZones[0])
        expect(getVisibleBoundaryIndexes()).toEqual([])

        fireEvent.mouseEnter(boundaryHoverZones[1])
        expect(getVisibleBoundaryIndexes()).toEqual(['1'])

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

    it('uses a line menu button for empty body rows instead of boundary add buttons', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')
        const lineInsertMenuButton = container.querySelector('.MarkdownNotebook__line-insert-menu-button')
        const editableTextBlock = getBodyTextBlock(container)

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

        const lineInsertMenuHitArea = container.querySelector('.MarkdownNotebook__line-insert-menu-hit-area')
        expect(lineInsertMenuHitArea).toBeInstanceOf(HTMLElement)

        fireEvent.mouseEnter(lineInsertMenuHitArea as HTMLElement)

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
        expect(container.querySelector('[data-placeholder="Start writing..."]')).toBeNull()
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
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)

        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
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
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

        expect(row).toBeInstanceOf(HTMLElement)
        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const textBlock = getBodyTextBlock(container)
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
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n `)
    })

    it('closes the slash menu when clicking outside it', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' ') }))
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

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
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

        expect(row).toBeInstanceOf(HTMLElement)
        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        const textBlock = getBodyTextBlock(container)
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
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onAskAI }))
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

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

        const editableTextBlock = getBodyTextBlock(container)
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
            markdown: `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n `,
            markdownWithPlaceholder: expect.any(String),
        })
        expect(aiRequest.insertionPlaceholder).toEqual(
            `<!-- Ask PostHog AI insertion placeholder block id: ${aiRequest.placeholderNodeId} -->`
        )
        expect(aiRequest.markdownWithPlaceholder).toEqual(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n${aiRequest.insertionPlaceholder}`
        )
    })

    it('removes a stuck AI thinking placeholder when selected and deleted', () => {
        const onAskAI = jest.fn()
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onAskAI, onChange })
        )
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = getBodyTextBlock(container)
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        const thinkingTag = container.querySelector('.MarkdownNotebook__ai-prompt-tag') as HTMLButtonElement

        expect(thinkingTag.textContent).toEqual('Thinking ...')

        fireEvent.click(thinkingTag)
        fireEvent.keyDown(thinkingTag, { key: 'Backspace' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith(TEST_NOTEBOOK_TITLE_MARKDOWN)
        expect(document.activeElement).toEqual(container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR))
        expect(window.getSelection()?.focusOffset).toEqual(TEST_NOTEBOOK_TITLE.length)
    })

    it('applies remote markdown updates while showing an AI thinking placeholder', async () => {
        const onAskAI = jest.fn()
        const onInteractionStateChange = jest.fn()
        const { container, rerender } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(' '),
                remoteValue: withNotebookTitle(' '),
                onAskAI,
                onInteractionStateChange,
            })
        )
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = getBodyTextBlock(container)
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.textContent).toEqual('Thinking ...')
        expect(onInteractionStateChange).toHaveBeenLastCalledWith(false)

        rerender(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(' '),
                remoteValue: withNotebookTitle('AI response'),
                onAskAI,
                onInteractionStateChange,
            })
        )

        await waitFor(() => {
            if (container.querySelector('.MarkdownNotebook__ai-prompt-tag')) {
                throw new Error('Expected AI prompt tag to be removed')
            }
        })
        expect(getBodyTextBlock(container).textContent).toEqual('AI response')
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
        const initialTextBlocks = Array.from(
            container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)
        ) as HTMLElement[]

        expect(initialTextBlocks.map((block) => block.textContent)).toEqual(['Before', '', 'After'])

        initialTextBlocks[1].textContent = '/'
        fireEvent.input(initialTextBlocks[1])
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        initialTextBlocks[1].textContent = 'Add a summary here'
        fireEvent.input(initialTextBlocks[1])
        fireEvent.keyDown(initialTextBlocks[1], { key: 'Enter' })

        const thinkingTag = container.querySelector('.MarkdownNotebook__ai-prompt-tag') as HTMLButtonElement
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]

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
        expect(onChange).toHaveBeenLastCalledWith(`# Before

After`)
    })

    it('creates a blank row below an AI thinking placeholder when clicking below the canvas', () => {
        const onAskAI = jest.fn()
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onAskAI, onChange })
        )
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = getBodyTextBlock(container)
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

        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.textContent).toEqual('Thinking ...')
        expect(textBlocks).toHaveLength(2)
        expect(document.activeElement).toEqual(textBlocks[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)
    })

    it('turns an Ask AI prompt back into regular text when backspacing at the start', () => {
        const onAskAI = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onAskAI }))
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

        fireEvent.mouseEnter(row as HTMLElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)

        const editableTextBlock = getBodyTextBlock(container)
        editableTextBlock.textContent = 'Add a summary here'
        fireEvent.input(editableTextBlock)
        selectTextInElement(editableTextBlock, 0, 0)
        fireEvent.keyDown(editableTextBlock, { key: 'Backspace' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')).toBeNull()
        expect(getBodyTextBlock(container).textContent).toEqual('Add a summary here')
    })

    it('adds heading blocks from slash menu h aliases', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const editableTextBlock = getBodyTextBlock(container)

        editableTextBlock.textContent = '/'
        fireEvent.input(editableTextBlock)

        editableTextBlock.textContent = 'h1'
        fireEvent.input(editableTextBlock)

        const filteredInsertItems = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item'))
        expect(filteredInsertItems.map((item) => item.textContent)).toEqual(['Heading 1'])
        expect(filteredInsertItems[0].getAttribute('aria-selected')).toEqual('true')

        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        const heading = getBodyTextBlock(container)
        expect(heading).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(heading)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n#`)
    })

    it('keeps newly inserted components active for keyboard row actions', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const row = getBodyTextBlock(container).closest('.MarkdownNotebook__row')

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

        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
        expect(textBlocks).toHaveLength(2)
        expect(document.activeElement).toEqual(textBlocks[1])

        shell.focus()
        expect(document.activeElement).toEqual(shell)

        fireEvent.keyDown(shell, { key: 'Backspace' })

        expect(container.querySelector('.MarkdownNotebook__component-shell')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n `)
    })

    it('positions the slash menu as a fixed popover within the viewport', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' ') }))
        const textBlock = getBodyTextBlock(container)

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
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Intro paragraph'), onChange })
        )
        const addBeforeButton = container.querySelector('.MarkdownNotebook__insert-boundary-button')

        expect(addBeforeButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(addBeforeButton as HTMLButtonElement)

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n \n\nIntro paragraph`)
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()

        const insertedTextBlock = getBodyTextBlock(container)
        insertedTextBlock.textContent = '/'
        fireEvent.input(insertedTextBlock)

        const trendButton = Array.from(container.querySelectorAll('.MarkdownNotebook__insert-item')).find(
            (button) => button.textContent === 'Trend'
        )

        expect(trendButton).toBeInstanceOf(HTMLButtonElement)
        fireEvent.click(trendButton as HTMLButtonElement)

        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining(`/>\n\nIntro paragraph`))
    })

    it('floats and closes the formatting toolbar based on the active text selection', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'Select this text' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)

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

    it('shows the formatting toolbar when selecting text across text rows', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph\n\nSecond paragraph' }))
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]

        selectTextAcrossNodes(getFirstTextNode(textBlocks[0]), 0, getFirstTextNode(textBlocks[1]), 6, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeInstanceOf(HTMLElement)
    })

    it('shows the shared block style for same-style text row selections', () => {
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('First paragraph\n\nSecond paragraph') })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextAcrossNodes(getFirstTextNode(textBlocks[1]), 0, getFirstTextNode(textBlocks[2]), 6, true)

        expect(getFormattingStyleButton(container).textContent?.trim()).toEqual('Text')
    })

    it('shows an empty block style for mixed text row selections', () => {
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('## First heading\n\nSecond paragraph') })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextAcrossNodes(getFirstTextNode(textBlocks[1]), 0, getFirstTextNode(textBlocks[2]), 6, true)

        expect(getFormattingStyleButton(container).textContent?.trim()).toEqual('')
    })

    it('delays the formatting toolbar after a mouse drag selection ends', () => {
        act(() => {
            window.getSelection()?.removeAllRanges()
        })
        jest.useFakeTimers()
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
        const textNode = getFirstTextNode(textBlock)
        const startRange = document.createRange()
        startRange.setStart(textNode, 0)
        startRange.collapse(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn(() => startRange),
        })

        fireEvent.mouseDown(textBlock, { button: 0, clientX: 10, clientY: 10 })
        selectTextNode(textNode, 0, 5, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeNull()

        fireEvent.mouseUp(window.document, { clientX: 180, clientY: 80 })

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeNull()

        act(() => {
            jest.advanceTimersByTime(199)
        })

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeNull()

        act(() => {
            jest.advanceTimersByTime(1)
        })

        const toolbar = container.querySelector('.MarkdownNotebook__format-toolbar')
        expect(toolbar).toBeInstanceOf(HTMLElement)
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-left')).toEqual(
            '180px'
        )
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-top')).toEqual(
            '88px'
        )
        expect(toolbar?.classList.contains('MarkdownNotebook__format-toolbar--below')).toBe(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
        jest.useRealTimers()
    })

    it('places the formatting toolbar above an upward mouse drag selection', () => {
        act(() => {
            window.getSelection()?.removeAllRanges()
        })
        jest.useFakeTimers()
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
        const textNode = getFirstTextNode(textBlock)
        const startRange = document.createRange()
        startRange.setStart(textNode, 0)
        startRange.collapse(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn(() => startRange),
        })

        fireEvent.mouseDown(textBlock, { button: 0, clientX: 180, clientY: 80 })
        selectTextNode(textNode, 0, 5, true)
        fireEvent.mouseUp(window.document, { clientX: 140, clientY: 20 })

        act(() => {
            jest.advanceTimersByTime(200)
        })

        const toolbar = container.querySelector('.MarkdownNotebook__format-toolbar')
        expect(toolbar).toBeInstanceOf(HTMLElement)
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-left')).toEqual(
            '140px'
        )
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-top')).toEqual(
            '20px'
        )
        expect(toolbar?.classList.contains('MarkdownNotebook__format-toolbar--above')).toBe(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
        jest.useRealTimers()
    })

    it('places the formatting toolbar near the last touch point after selection', () => {
        act(() => {
            window.getSelection()?.removeAllRanges()
        })
        jest.useFakeTimers()
        const caretDocument = document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }
        const originalCaretRangeFromPoint = caretDocument.caretRangeFromPoint
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
        const textNode = getFirstTextNode(textBlock)
        const startRange = document.createRange()
        startRange.setStart(textNode, 0)
        startRange.collapse(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: jest.fn(() => startRange),
        })

        const startTouch = { identifier: 1, clientX: 20, clientY: 20 } as Touch
        const endTouch = { identifier: 1, clientX: 160, clientY: 70 } as Touch

        fireEvent.touchStart(textBlock, {
            touches: createTouchList([startTouch]),
            changedTouches: createTouchList([startTouch]),
        })
        selectTextNode(textNode, 0, 5, true)
        fireEvent.touchEnd(window.document, {
            touches: createTouchList([]),
            changedTouches: createTouchList([endTouch]),
        })

        act(() => {
            jest.advanceTimersByTime(200)
        })

        const toolbar = container.querySelector('.MarkdownNotebook__format-toolbar')
        expect(toolbar).toBeInstanceOf(HTMLElement)
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-left')).toEqual(
            '160px'
        )
        expect((toolbar as HTMLElement).style.getPropertyValue('--markdown-notebook-format-toolbar-top')).toEqual(
            '78px'
        )
        expect(toolbar?.classList.contains('MarkdownNotebook__format-toolbar--below')).toBe(true)

        Object.defineProperty(document, 'caretRangeFromPoint', {
            configurable: true,
            value: originalCaretRangeFromPoint,
        })
        jest.useRealTimers()
    })

    it('applies inline formatting across selected text rows', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: 'First paragraph\n\nSecond paragraph', onChange })
        )
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]

        selectTextAcrossNodes(getFirstTextNode(textBlocks[0]), 0, getFirstTextNode(textBlocks[1]), 6, true)
        const boldButton = container.querySelector('button[aria-label="Bold"]') as HTMLButtonElement
        fireEvent.click(boldButton)

        expect(onChange).toHaveBeenLastCalledWith('# **First paragraph**\n\n**Second** paragraph')
        expect(window.getSelection()?.toString()).toContain('First paragraph')
        expect(window.getSelection()?.toString()).toContain('Second')

        fireEvent.click(boldButton)

        expect(onChange).toHaveBeenLastCalledWith('# First paragraph\n\nSecond paragraph')
    })

    it('normalizes mixed inline formatting across selected text rows', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: 'First **paragraph**\n\nSecond paragraph', onChange })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextAcrossNodes(getFirstTextNode(textBlocks[0]), 0, getFirstTextNode(textBlocks[1]), 6, true)
        const boldButton = container.querySelector('button[aria-label="Bold"]') as HTMLButtonElement
        fireEvent.click(boldButton)

        expect(onChange).toHaveBeenLastCalledWith('# **First paragraph**\n\n**Second** paragraph')

        fireEvent.click(boldButton)

        expect(onChange).toHaveBeenLastCalledWith('# First paragraph\n\nSecond paragraph')
    })

    it('selects the notebook contents with Cmd+A and applies a formatting shortcut', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle('First paragraph\n\nSecond paragraph'),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        fireEvent.keyDown(textBlocks[1], { key: 'a', metaKey: true })
        fireEvent.keyDown(textBlocks[1], { key: 'b', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN.replace(TEST_NOTEBOOK_TITLE, `**${TEST_NOTEBOOK_TITLE}**`)}\n\n**First paragraph**\n\n**Second paragraph**`
        )
    })

    it('selects text and components with Cmd+A from a focused component', () => {
        const onChange = jest.fn()
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
                value: withNotebookTitle(`Before paragraph

<Embed />

After paragraph`),
                onChange,
                registry,
            })
        )
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const component = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement

        component.focus()
        fireEvent.keyDown(component, { key: 'a', metaKey: true })

        expect(window.getSelection()?.toString()).toContain(TEST_NOTEBOOK_TITLE)
        expect(window.getSelection()?.toString()).toContain('Before paragraph')
        expect(window.getSelection()?.toString()).toContain('After paragraph')
        expect(component.classList.contains('MarkdownNotebook__component-shell--selected')).toBe(true)

        const clipboardData = {
            setData: jest.fn(),
        }
        fireEvent.copy(notebook, { clipboardData })

        expect(clipboardData.setData).toHaveBeenCalledWith(
            'text/plain',
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}

Before paragraph

<Embed />

After paragraph`
        )
        expect(clipboardData.setData).not.toHaveBeenCalledWith('text/plain', expect.stringContaining('Do not copy me'))

        fireEvent.keyDown(component, { key: 'b', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN.replace(
            TEST_NOTEBOOK_TITLE,
            `**${TEST_NOTEBOOK_TITLE}**`
        )}

**Before paragraph**

<Embed />

**After paragraph**`)
    })

    it('normalizes mixed bold and unbold text when select-all Cmd+B is pressed repeatedly', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`Alpha **bold** plain

**Second** mixed row`),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        fireEvent.keyDown(textBlocks[1], { key: 'a', metaKey: true })
        fireEvent.keyDown(textBlocks[1], { key: 'b', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN.replace(
            TEST_NOTEBOOK_TITLE,
            `**${TEST_NOTEBOOK_TITLE}**`
        )}

**Alpha bold plain**

**Second mixed row**`)

        fireEvent.keyDown(textBlocks[1], { key: 'b', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

Alpha bold plain

Second mixed row`)

        fireEvent.keyDown(textBlocks[1], { key: 'b', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN.replace(
            TEST_NOTEBOOK_TITLE,
            `**${TEST_NOTEBOOK_TITLE}**`
        )}

**Alpha bold plain**

**Second mixed row**`)
    })

    it('supports Ctrl+A as the non-Apple select-all shortcut', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle('First paragraph\n\nSecond paragraph'),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        fireEvent.keyDown(textBlocks[1], { key: 'a', ctrlKey: true })
        fireEvent.keyDown(textBlocks[1], { key: 'u', ctrlKey: true })

        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN.replace(TEST_NOTEBOOK_TITLE, `<u>${TEST_NOTEBOOK_TITLE}</u>`)}\n\n<u>First paragraph</u>\n\n<u>Second paragraph</u>`
        )
    })

    it('applies keyboard inline formatting shortcuts to selected text', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle('Bold line\n\nItalic line\n\nUnderline line'),
                onChange,
            })
        )
        let textBlocks = getEditableTextBlocks(container)

        selectTextInElement(textBlocks[1], 0, 'Bold'.length)
        fireEvent.keyDown(textBlocks[1], { key: 'b', metaKey: true })
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n**Bold** line\n\nItalic line\n\nUnderline line`
        )

        textBlocks = getEditableTextBlocks(container)
        selectTextInElement(textBlocks[2], 0, 'Italic'.length)
        fireEvent.keyDown(textBlocks[2], { key: 'i', ctrlKey: true })
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n**Bold** line\n\n*Italic* line\n\nUnderline line`
        )

        textBlocks = getEditableTextBlocks(container)
        selectTextInElement(textBlocks[3], 0, 'Underline'.length)
        fireEvent.keyDown(textBlocks[3], { key: 'u', metaKey: true })
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n**Bold** line\n\n*Italic* line\n\n<u>Underline</u> line`
        )
    })

    it('applies Ctrl and uppercase inline formatting shortcuts to selected text', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle('Bold line\n\nItalic line\n\nUnderline line'),
                onChange,
            })
        )
        let textBlocks = getEditableTextBlocks(container)

        selectTextInElement(textBlocks[1], 0, 'Bold'.length)
        fireEvent.keyDown(textBlocks[1], { key: 'b', ctrlKey: true })
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n**Bold** line\n\nItalic line\n\nUnderline line`
        )

        textBlocks = getEditableTextBlocks(container)
        selectTextInElement(textBlocks[2], 0, 'Italic'.length)
        fireEvent.keyDown(textBlocks[2], { key: 'I', metaKey: true })
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n**Bold** line\n\n*Italic* line\n\nUnderline line`
        )

        textBlocks = getEditableTextBlocks(container)
        selectTextInElement(textBlocks[3], 0, 'Underline'.length)
        fireEvent.keyDown(textBlocks[3], { key: 'u', ctrlKey: true })
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n**Bold** line\n\n*Italic* line\n\n<u>Underline</u> line`
        )
    })

    it('ignores shifted inline formatting shortcuts', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Plain line'), onChange })
        )
        const textBlock = getBodyTextBlock(container)

        selectTextInElement(textBlock, 0, 'Plain'.length)
        fireEvent.keyDown(textBlock, { key: 'b', metaKey: true, shiftKey: true })

        expect(onChange).not.toHaveBeenCalled()
    })

    it('applies block style across selected text rows and preserves selection', async () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle('First paragraph\n\nSecond paragraph'),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextAcrossNodes(getFirstTextNode(textBlocks[1]), 0, getFirstTextNode(textBlocks[2]), 6, true)
        fireEvent.click(getFormattingStyleButton(container))
        fireEvent.click(await waitForFormattingStyleMenuItem('Heading 2'))

        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n## First paragraph\n\n## Second paragraph`
        )
        expect(window.getSelection()?.toString()).toContain('First paragraph')
        expect(window.getSelection()?.toString()).toContain('Second')
    })

    it('keeps the formatting toolbar position fixed while toolbar actions update selected text', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'First paragraph' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement

        selectTextNode(getFirstTextNode(textBlock), 0, 5, true)

        const toolbar = container.querySelector('.MarkdownNotebook__format-toolbar') as HTMLElement
        expect(toolbar.style.getPropertyValue('--markdown-notebook-format-toolbar-left')).toEqual('140px')
        expect(toolbar.style.getPropertyValue('--markdown-notebook-format-toolbar-top')).toEqual('100px')

        const boldButton = container.querySelector('button[aria-label="Bold"]') as HTMLButtonElement
        fireEvent.mouseDown(boldButton)
        fireEvent.click(boldButton)

        selectTextNodeWithRect(getFirstTextNode(textBlock), 0, 5, {
            bottom: 240,
            height: 20,
            left: 300,
            right: 460,
            top: 220,
            width: 160,
            x: 300,
            y: 220,
            toJSON: () => ({}),
        } as DOMRect)

        const lockedToolbar = container.querySelector('.MarkdownNotebook__format-toolbar') as HTMLElement
        expect(lockedToolbar.style.getPropertyValue('--markdown-notebook-format-toolbar-left')).toEqual('140px')
        expect(lockedToolbar.style.getPropertyValue('--markdown-notebook-format-toolbar-top')).toEqual('100px')
    })

    it('asks AI about highlighted text from the formatting toolbar', () => {
        const onAskAI = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: 'First paragraph\n\nSecond paragraph', onAskAI })
        )
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]

        selectTextAcrossNodes(getFirstTextNode(textBlocks[0]), 0, getFirstTextNode(textBlocks[1]), 6, true)
        fireEvent.click(container.querySelector('button[aria-label="Ask AI"]') as HTMLButtonElement)

        const aiRequest = onAskAI.mock.calls[0][0]
        expect(aiRequest.query).toContain('Highlighted markdown:')
        expect(aiRequest.query).toContain('# First paragraph\n\nSecond')
        expect(aiRequest.query).toContain('replace the highlighted content')
        expect(aiRequest.markdown).toEqual('# First paragraph\n\nSecond paragraph')
        expect(aiRequest.insertionPlaceholder).toEqual(
            `<!-- Ask PostHog AI insertion placeholder block id: ${aiRequest.placeholderNodeId} -->`
        )
        expect(aiRequest.markdownWithPlaceholder).toContain(aiRequest.insertionPlaceholder)
        expect(aiRequest.markdownWithPlaceholder).toContain(`${aiRequest.insertionPlaceholder}First paragraph`)
    })

    it('adds a link from the formatting toolbar', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'PostHog docs', onChange }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement

        selectTextNode(getFirstTextNode(textBlock), 0, 7, true)
        fireEvent.click(container.querySelector('button[aria-label="Link"]') as HTMLButtonElement)

        const linkInput = container.querySelector('input[aria-label="Link URL"]') as HTMLInputElement

        expect(linkInput).toBeInstanceOf(HTMLInputElement)
        fireEvent.change(linkInput, { target: { value: 'https://posthog.com/docs' } })
        fireEvent.keyDown(linkInput, { key: 'Enter' })

        expect(textBlock.querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(onChange).toHaveBeenLastCalledWith('# [PostHog](https://posthog.com/docs) docs')
    })

    it('edits an existing link from the formatting toolbar', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: '[PostHog](https://posthog.com) docs', onChange })
        )
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
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
        expect(onChange).toHaveBeenLastCalledWith('# [PostHog](https://posthog.com/docs) docs')
    })

    it('does not open the link editor for a collapsed selection inside an existing link', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: '[PostHog](https://posthog.com) docs' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
        const linkedTextNode = textBlock.querySelector('a')?.firstChild

        expect(linkedTextNode).toBeInstanceOf(Text)

        selectTextNode(linkedTextNode as Text, 3, 3, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeNull()
        expect(container.querySelector('input[aria-label="Link URL"]')).toBeNull()
        expect(document.activeElement).not.toBeInstanceOf(HTMLInputElement)
    })

    it('shows the formatting toolbar when selecting text on a line containing a link', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: '[PostHog](https://posthog.com) docs' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
        const textAfterLink = textBlock.lastChild

        expect(textAfterLink).toBeInstanceOf(Text)

        selectTextNode(textAfterLink as Text, 1, 5, true)

        expect(container.querySelector('.MarkdownNotebook__format-toolbar')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('input[aria-label="Link URL"]')).toBeNull()
    })

    it('keeps the formatting toolbar available after adding or removing a link on the row', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: 'PostHog docs' }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement

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
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Hello selected text tail'), onChange })
        )
        const textBlock = getBodyTextBlock(container)

        selectTextInElement(textBlock, 6, 19)
        fireEvent.keyDown(textBlock, { key: 'Enter' })

        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
        expect(textBlocks.map((block) => block.textContent)).toEqual([TEST_NOTEBOOK_TITLE, 'Hello ', ' tail'])
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nHello \n\n tail`)
        expect(document.activeElement).toEqual(textBlocks[2])
    })

    it('deletes selected text with Backspace through notebook history', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Hello selected text tail'), onChange })
        )
        const textBlock = getBodyTextBlock(container)

        selectTextInElement(textBlock, 6, 19)
        fireEvent.keyDown(textBlock, { key: 'Backspace' })

        expect(textBlock.textContent).toEqual('Hello  tail')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nHello  tail`)

        fireEvent.keyDown(textBlock, { key: 'z', metaKey: true })

        expect(getBodyTextBlock(container).textContent).toEqual('Hello selected text tail')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nHello selected text tail`)
    })

    it('clears a focused row when all row text is selected and Backspace is pressed', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Delete me'), onChange })
        )
        const textBlock = getBodyTextBlock(container)

        textBlock.focus()
        selectElementContents(textBlock)
        fireEvent.keyDown(textBlock, { key: 'Backspace' })

        expect(textBlock.textContent).toEqual('')
        expect(document.activeElement).toEqual(textBlock)
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n `)
    })

    it('clears a row when the selection wraps the whole editable row element', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`Keep

Delete me

After`),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        textBlocks[2].focus()
        selectAroundElement(textBlocks[2])
        fireEvent.keyDown(textBlocks[2], { key: 'Backspace' })

        expect(textBlocks.map((block) => block.textContent)).toEqual([TEST_NOTEBOOK_TITLE, 'Keep', '', 'After'])
        expect(document.activeElement).toEqual(textBlocks[2])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}

Keep

${' '}

After`
        )
    })

    it('deletes multiple selected text blocks with Backspace', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`Keep before

Delete one

Delete two

Keep after`),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextAcrossNodes(getFirstTextNode(textBlocks[2]), 0, getFirstTextNode(textBlocks[3]), 'Delete two'.length)
        fireEvent.keyDown(textBlocks[2], { key: 'Backspace' })

        const nextTextBlocks = getEditableTextBlocks(container)
        expect(nextTextBlocks.map((block) => block.textContent)).toEqual([
            TEST_NOTEBOOK_TITLE,
            'Keep before',
            'Keep after',
        ])
        expect(document.activeElement).toEqual(nextTextBlocks[2])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nKeep before\n\nKeep after`)
    })

    it('deletes a Cmd+A selection that includes component blocks', () => {
        const onChange = jest.fn()
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Embed',
                label: 'Embed',
                category: 'Media',
                ViewComponent: () => createElement('div', { 'data-testid': 'component-output' }, 'Do not delete me'),
            },
        ])
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`Before paragraph

<Embed />

After paragraph`),
                onChange,
                registry,
            })
        )
        const component = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement

        component.focus()
        fireEvent.keyDown(component, { key: 'a', metaKey: true })
        fireEvent.keyDown(component, { key: 'Backspace' })

        const nextTextBlocks = getEditableTextBlocks(container)
        expect(nextTextBlocks.map((block) => block.textContent)).toEqual([''])
        expect(document.activeElement).toEqual(nextTextBlocks[0])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith('#')
    })

    it('merges a text row into the previous text row with Backspace and supports undo', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`First row

Second row`),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextInElement(textBlocks[2], 0, 0)
        fireEvent.keyDown(textBlocks[2], { key: 'Backspace' })

        expect(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)).toHaveLength(2)
        expect(getBodyTextBlock(container).textContent).toEqual('First rowSecond row')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nFirst rowSecond row`)

        fireEvent.keyDown(getBodyTextBlock(container), {
            key: 'z',
            metaKey: true,
        })

        const restoredTextBlocks = getEditableTextBlocks(container)
        expect(restoredTextBlocks.map((block) => block.textContent)).toEqual([
            TEST_NOTEBOOK_TITLE,
            'First row',
            'Second row',
        ])
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

First row

Second row`)
    })

    it('uses the canvas as the native editable surface and keeps component atoms non-editable', () => {
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Embed',
                label: 'Embed',
                category: 'Media',
                ViewComponent: () => createElement('div', null, 'Embedded output'),
            },
        ])
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

<Embed />

Second paragraph`,
                registry,
            })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas')
        const component = container.querySelector('.MarkdownNotebook__component-shell')

        expect(canvas?.getAttribute('contenteditable')).toEqual('true')
        expect(canvas?.getAttribute('data-markdown-notebook-editor')).toEqual('true')
        expect(component?.getAttribute('contenteditable')).toEqual('false')
    })

    it('keeps notebook tool UI non-editable inside the editable canvas', () => {
        const onAskAI = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`First paragraph

 `),
                onAskAI,
            })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const textBlock = getBodyTextBlock(container)
        const blankBlock = getBodyTextBlock(container, 1)

        expect(canvas.getAttribute('contenteditable')).toEqual('true')

        selectTextNode(getFirstTextNode(textBlock), 0, 'First'.length, true)
        expect(container.querySelector('.MarkdownNotebook__format-toolbar')?.getAttribute('contenteditable')).toEqual(
            'false'
        )

        fireEvent.mouseEnter(blankBlock.closest('.MarkdownNotebook__row') as HTMLElement)
        const lineInsertMenuHitArea = container.querySelector('.MarkdownNotebook__line-insert-menu-hit-area')
        expect(lineInsertMenuHitArea?.getAttribute('contenteditable')).toEqual('false')

        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)
        expect(container.querySelector('.MarkdownNotebook__insert-menu')?.getAttribute('contenteditable')).toEqual(
            'false'
        )

        fireEvent.click(container.querySelector('.MarkdownNotebook__insert-item') as HTMLButtonElement)
        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.getAttribute('contenteditable')).toEqual(
            'false'
        )

        const editableBlocks = getEditableTextBlocks(container)
        const aiPromptBlock = editableBlocks[editableBlocks.length - 1]
        expect(aiPromptBlock.getAttribute('contenteditable')).toEqual('true')

        aiPromptBlock.textContent = 'Add a summary here'
        fireEvent.input(aiPromptBlock)
        fireEvent.keyDown(aiPromptBlock, { key: 'Enter' })

        expect(container.querySelector('.MarkdownNotebook__ai-prompt-tag')?.getAttribute('contenteditable')).toEqual(
            'false'
        )
        expect(
            container
                .querySelector('.MarkdownNotebook__text-row--ai-thinking .MarkdownNotebook__text-block')
                ?.getAttribute('contenteditable')
        ).toEqual('false')
    })

    it('syncs text edits when native input is dispatched from the root editable surface', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Original text', onChange }))
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement

        textBlock.innerHTML = 'Changed <strong>text</strong>'
        act(() => {
            const range = document.createRange()
            range.selectNodeContents(textBlock)
            range.collapse(false)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })
        fireEvent.input(canvas)

        expect(onChange).toHaveBeenLastCalledWith('# Changed **text**')
    })

    it('preserves native br linebreaks when editing a text block', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Original'), onChange })
        )
        const textBlock = getBodyTextBlock(container)

        textBlock.innerHTML = 'First<br>Second<br />Third'
        act(() => {
            const range = document.createRange()
            range.selectNodeContents(textBlock)
            range.collapse(false)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })
        fireEvent.input(textBlock)

        expect(textBlock.querySelectorAll('br')).toHaveLength(2)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nFirst\nSecond\nThird`)
    })

    it('preserves native div and paragraph linebreaks when editing a text block', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Original'), onChange })
        )
        const textBlock = getBodyTextBlock(container)

        textBlock.innerHTML = 'First<div>Second</div><p>Third</p>'
        act(() => {
            const range = document.createRange()
            range.selectNodeContents(textBlock)
            range.collapse(false)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })
        fireEvent.input(textBlock)

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nFirst\nSecond\nThird`)
    })

    it('opens the slash menu when native slash input is dispatched from the root editable surface', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const textBlock = getBodyTextBlock(container)

        textBlock.textContent = '/'
        act(() => {
            const range = document.createRange()
            range.selectNodeContents(textBlock)
            range.collapse(false)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })
        fireEvent.input(canvas)

        expect(textBlock.textContent).toEqual('')
        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(
            container.querySelector('.MarkdownNotebook__line-insert-menu-button')?.getAttribute('aria-expanded')
        ).toEqual('true')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n `)
    })

    it('derives component active state and copy payload from native root selections', () => {
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
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
        const component = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement

        selectTextAcrossNodes(getFirstTextNode(textBlocks[0]), 3, getFirstTextNode(textBlocks[1]), 5, true)

        expect(window.getSelection()?.toString()).toContain('ore paragraph')
        expect(window.getSelection()?.toString()).toContain('After')
        expect(component.classList.contains('MarkdownNotebook__component-shell--selected')).toBe(true)

        const clipboardData = {
            setData: jest.fn(),
        }
        fireEvent.copy(notebook, { clipboardData })

        expect(clipboardData.setData).toHaveBeenCalledWith(
            'text/plain',
            `# ore paragraph

<Embed />

After`
        )
        expect(clipboardData.setData).not.toHaveBeenCalledWith('text/plain', expect.stringContaining('Do not copy me'))
    })

    it('lets native touch movement scroll without custom selection interception', () => {
        act(() => {
            window.getSelection()?.removeAllRanges()
        })
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]

        const startTouch = { identifier: 1, clientX: 40, clientY: 40 } as Touch
        const moveTouch = { identifier: 1, clientX: 10, clientY: 4 } as Touch

        fireEvent.touchStart(textBlocks[1], {
            touches: createTouchList([startTouch]),
            changedTouches: createTouchList([startTouch]),
        })

        expect(
            fireEvent.touchMove(window.document, {
                touches: createTouchList([moveTouch]),
                changedTouches: createTouchList([moveTouch]),
            })
        ).toBe(true)

        expect(window.getSelection()?.toString() ?? '').toEqual('')
        expect(textBlocks[0].getAttribute('contenteditable')).toEqual('true')
        expect(textBlocks[1].getAttribute('contenteditable')).toEqual('true')

        fireEvent.touchEnd(window.document, {
            touches: createTouchList([]),
            changedTouches: createTouchList([moveTouch]),
        })
    })

    it('keeps text visible when changing a paragraph to a heading', () => {
        const { container, rerender } = render(createElement(MarkdownNotebook, { value: 'Selected heading text' }))

        expect(container.querySelector('h1.MarkdownNotebook__text-block')?.textContent).toEqual('Selected heading text')

        rerender(createElement(MarkdownNotebook, { value: '# Selected heading text' }))

        expect(container.querySelector('h1.MarkdownNotebook__text-block')?.textContent).toEqual('Selected heading text')
    })

    it('copies selected notebook content as markdown including components', () => {
        const markdown = `Intro paragraph

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />

Closing paragraph`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const notebook = container.querySelector('.MarkdownNotebook') as HTMLElement
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
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
            `# paragraph

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />

Closing`
        )
        expect(clipboardData.setData).toHaveBeenCalledWith(
            'text/markdown',
            `# paragraph

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
            expect(onChange).toHaveBeenLastCalledWith(`# \n\n${markdown}\n\n${markdown}`)
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
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const textBlock = getBodyTextBlock(container)

        fireEvent.paste(textBlock, {
            clipboardData: {
                getData: jest.fn((type: string) => (type === 'text/plain' ? pastedMarkdown : '')),
            },
        })

        expect(getEditableTextBlocks(container)[1].textContent).toEqual('Pasted heading')
        expect(container.querySelector('.MarkdownNotebook__component-shell')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('p.MarkdownNotebook__text-block')?.textContent).toEqual('Tail with bold text')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n${pastedMarkdown}`)
    })

    it('pastes inline markdown into the active text block', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Hello ', onChange }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement
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
        expect(onChange).toHaveBeenLastCalledWith('# Hello **bold**')
    })

    it('undoes pasted markdown blocks as one notebook history step', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('Intro paragraph'), onChange })
        )
        const textBlock = getBodyTextBlock(container)
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

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

Intro paragraph

# Pasted heading

Tail with **bold** text`)

        fireEvent.keyDown(textBlock, { key: 'z', metaKey: true })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nIntro paragraph`)
        expect(container.querySelector('.MarkdownNotebook__component-shell')).toBeNull()
        expect(getBodyTextBlock(container).textContent).toEqual('Intro paragraph')
    })

    it('routes native contenteditable undo and redo through notebook history after paste', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'Hello there', onChange }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement

        selectTextInElement(textBlock, 6, 6)
        pastePlainText(textBlock, '**bold** ')

        expect(onChange).toHaveBeenLastCalledWith('# Hello **bold** there')
        expect(textBlock.textContent).toEqual('Hello bold there')

        fireHistoryBeforeInput(textBlock, 'historyUndo')

        expect(onChange).toHaveBeenLastCalledWith('# Hello there')
        expect(container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)?.textContent).toEqual('Hello there')

        fireHistoryBeforeInput(container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement, 'historyRedo')

        expect(onChange).toHaveBeenLastCalledWith('# Hello **bold** there')
        expect(container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)?.textContent).toEqual('Hello bold there')
    })

    it('pastes a URL over selected text as a link', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: 'PostHog docs', onChange }))
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR) as HTMLElement

        selectTextInElement(textBlock, 0, 7)
        pastePlainText(textBlock, 'https://posthog.com/docs')

        expect(textBlock.querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(textBlock.textContent).toEqual('PostHog docs')
        expect(onChange).toHaveBeenLastCalledWith('# [PostHog](https://posthog.com/docs) docs')
    })

    it('pastes a URL over selected list item text as a link', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('- PostHog docs'), onChange })
        )
        const listItem = container.querySelector('.MarkdownNotebook__list-item-content') as HTMLElement

        selectTextInElement(listItem, 0, 7)
        pastePlainText(listItem, 'https://posthog.com/docs')

        expect(listItem.querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(listItem.textContent).toEqual('PostHog docs')
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n- [PostHog](https://posthog.com/docs) docs`
        )
    })

    it('pastes a URL over selected table cell text as a link', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`| Name | Count |
| --- | --- |
| PostHog | 12 |`),
                onChange,
            })
        )
        const cells = Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content')) as HTMLElement[]

        selectTextInElement(cells[2], 0, 7)
        pastePlainText(cells[2], 'https://posthog.com/docs')

        expect(cells[2].querySelector('a')?.getAttribute('href')).toEqual('https://posthog.com/docs')
        expect(cells[2].textContent).toEqual('PostHog')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

| Name | Count |
| --- | --- |
| [PostHog](https://posthog.com/docs) | 12 |`)
    })

    it('renders nested lists as editable list items', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`- Parent
  - Child
- Sibling`),
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

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

- Parent
  - Updated child
- Sibling`)
    })

    it('converts an ordered list shortcut at the start of a text row into a list', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const textBlock = getBodyTextBlock(container)

        textBlock.textContent = '1. '
        fireEvent.input(textBlock)

        const listBlock = container.querySelector('.MarkdownNotebook__list-block')
        const listItem = container.querySelector('.MarkdownNotebook__list-item-content')

        expect(listBlock?.querySelector('ol')).toBeInstanceOf(HTMLElement)
        expect(listItem).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(listItem)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n1.`)
    })

    it.each(['- ', '* ', '+ ', '• '])(
        'converts a bullet list shortcut "%s" at the start of a text row into a list',
        (shortcut) => {
            const onChange = jest.fn()
            const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
            const textBlock = getBodyTextBlock(container)

            textBlock.textContent = shortcut
            fireEvent.input(textBlock)

            const listBlock = container.querySelector('.MarkdownNotebook__list-block')
            const listItem = container.querySelector('.MarkdownNotebook__list-item-content')

            expect(listBlock?.querySelector('ul')).toBeInstanceOf(HTMLElement)
            expect(listItem).toBeInstanceOf(HTMLElement)
            expect(document.activeElement).toEqual(listItem)
            expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n-`)
        }
    )

    it('converts repeated heading shortcuts into heading levels up to h3', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))

        let textBlock = getBodyTextBlock(container)
        textBlock.textContent = '#'
        fireEvent.input(textBlock)

        expect(getBodyTextBlock(container).tagName).toEqual('H1')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n#`)

        textBlock = getBodyTextBlock(container)
        textBlock.textContent = '#'
        fireEvent.input(textBlock)

        expect(getBodyTextBlock(container).tagName).toEqual('H2')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n##`)

        textBlock = getBodyTextBlock(container)
        textBlock.textContent = '#'
        fireEvent.input(textBlock)

        expect(getBodyTextBlock(container).tagName).toEqual('H3')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n###`)

        fireEvent.keyDown(getBodyTextBlock(container), { key: 'Backspace' })

        expect(container.querySelector('p.MarkdownNotebook__text-block')).toBeInstanceOf(HTMLElement)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n `)
    })

    it('splits headings while preserving heading style except at the start', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('# HelloWorld'), onChange })
        )
        let heading = getBodyTextBlock(container)

        selectTextInElement(heading, 5, 5)
        fireEvent.keyDown(heading, { key: 'Enter' })

        expect(
            Array.from(container.querySelectorAll('h1.MarkdownNotebook__text-block')).map((node) => node.textContent)
        ).toEqual([TEST_NOTEBOOK_TITLE, 'Hello', 'World'])
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

# Hello

# World`)

        heading = getBodyTextBlock(container)
        selectTextInElement(heading, 0, 0)
        fireEvent.keyDown(heading, { key: 'Enter' })

        const textBlocks = getEditableTextBlocks(container)

        expect(textBlocks[1].tagName).toEqual('P')
        expect(textBlocks[1].textContent).toEqual('')
        expect(textBlocks[2].tagName).toEqual('H1')
        expect(textBlocks[2].textContent).toEqual('Hello')
    })

    it('converts a blockquote shortcut at the start of a text row into a quote block', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const textBlock = getBodyTextBlock(container)

        textBlock.textContent = '>'
        fireEvent.input(textBlock)

        const blockquote = container.querySelector('blockquote.MarkdownNotebook__text-block')

        expect(blockquote).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(blockquote)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n>`)
    })

    it('continues a blockquote when pressing Enter in the middle of the quote', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('> QuoteTail'), onChange })
        )
        const blockquote = container.querySelector('blockquote.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(blockquote, 'Quote'.length, 'Quote'.length)
        fireEvent.keyDown(blockquote, { key: 'Enter' })

        const quotes = Array.from(
            container.querySelectorAll('blockquote.MarkdownNotebook__text-block')
        ) as HTMLElement[]
        expect(quotes.map((quote) => quote.textContent)).toEqual(['Quote', 'Tail'])
        expect(document.activeElement).toEqual(quotes[1])
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n> Quote\n\n> Tail`)
    })

    it('continues a blockquote when native insertParagraph splits the quote', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('> QuoteTail'), onChange })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const blockquote = container.querySelector('blockquote.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(blockquote, 'Quote'.length, 'Quote'.length)
        fireBeforeInput(canvas, 'insertParagraph')

        const quotes = Array.from(
            container.querySelectorAll('blockquote.MarkdownNotebook__text-block')
        ) as HTMLElement[]
        expect(quotes.map((quote) => quote.textContent)).toEqual(['Quote', 'Tail'])
        expect(document.activeElement).toEqual(quotes[1])
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n> Quote\n\n> Tail`)
    })

    it('merges continued blockquote parts with Backspace', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('> QuoteTail'), onChange })
        )
        let blockquote = container.querySelector('blockquote.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(blockquote, 'Quote'.length, 'Quote'.length)
        fireEvent.keyDown(blockquote, { key: 'Enter' })

        let quotes = Array.from(container.querySelectorAll('blockquote.MarkdownNotebook__text-block')) as HTMLElement[]
        selectTextInElement(quotes[1], 0, 0)
        fireEvent.keyDown(quotes[1], { key: 'Backspace' })

        quotes = Array.from(container.querySelectorAll('blockquote.MarkdownNotebook__text-block')) as HTMLElement[]
        blockquote = quotes[0]
        expect(quotes).toHaveLength(1)
        expect(blockquote.textContent).toEqual('QuoteTail')
        expect(document.activeElement).toEqual(blockquote)
        expect(window.getSelection()?.focusOffset).toEqual('Quote'.length)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n> QuoteTail`)
    })

    it('merges native continued blockquote parts with deleteContentBackward', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('> QuoteTail'), onChange })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        const blockquote = container.querySelector('blockquote.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(blockquote, 'Quote'.length, 'Quote'.length)
        fireBeforeInput(canvas, 'insertParagraph')

        let quotes = Array.from(container.querySelectorAll('blockquote.MarkdownNotebook__text-block')) as HTMLElement[]
        selectTextInElement(quotes[1], 0, 0)
        fireBeforeInput(canvas, 'deleteContentBackward')

        quotes = Array.from(container.querySelectorAll('blockquote.MarkdownNotebook__text-block')) as HTMLElement[]
        expect(quotes).toHaveLength(1)
        expect(quotes[0].textContent).toEqual('QuoteTail')
        expect(document.activeElement).toEqual(quotes[0])
        expect(window.getSelection()?.focusOffset).toEqual('Quote'.length)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n> QuoteTail`)
    })

    it('turns a blockquote back into a paragraph with Backspace at the start', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('> Quoted text'), onChange })
        )
        const blockquote = container.querySelector('blockquote.MarkdownNotebook__text-block') as HTMLElement

        selectTextInElement(blockquote, 0, 0)
        fireEvent.keyDown(blockquote, { key: 'Backspace' })

        const paragraph = getBodyTextBlock(container)
        expect(paragraph.tagName).toEqual('P')
        expect(paragraph.textContent).toEqual('Quoted text')
        expect(document.activeElement).toEqual(paragraph)
        expect(window.getSelection()?.focusOffset).toEqual(0)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nQuoted text`)
    })

    it('keeps the heading caret stable through repeated Enter and Backspace splits before appending text', () => {
        const onChange = jest.fn()
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle('# title'), onChange }))
        let textBlocks = getEditableTextBlocks(container)

        selectTextInElement(textBlocks[1], 'ti'.length, 'ti'.length)
        fireEvent.keyDown(textBlocks[1], { key: 'Enter' })

        textBlocks = getEditableTextBlocks(container)
        selectTextInElement(textBlocks[2], 0, 0)
        fireEvent.keyDown(textBlocks[2], { key: 'Backspace' })

        textBlocks = getEditableTextBlocks(container)
        expect(textBlocks[1].tagName).toEqual('H1')
        expect(textBlocks[1].textContent).toEqual('title')
        expect(window.getSelection()?.focusOffset).toEqual('ti'.length)

        fireEvent.keyDown(textBlocks[1], { key: 'Enter' })
        textBlocks = getEditableTextBlocks(container)
        selectTextInElement(textBlocks[2], 0, 0)
        fireEvent.keyDown(textBlocks[2], { key: 'Backspace' })

        textBlocks = getEditableTextBlocks(container)
        expect(textBlocks[1].textContent).toEqual('title')
        expect(window.getSelection()?.focusOffset).toEqual('ti'.length)

        selectTextInElement(textBlocks[1], 'title'.length, 'title'.length)
        textBlocks[1].textContent = 'titleasdf'
        fireEvent.input(textBlocks[1])

        expect(getEditableTextBlocks(container)[1].textContent).toEqual('titleasdf')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n# titleasdf`)
    })

    it('deletes a partial multi-block selection with Delete while preserving unselected text edges', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`Keep before

Alpha remove

Middle removed

remove Omega

Keep after`),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextAcrossNodes(
            getFirstTextNode(textBlocks[2]),
            'Alpha '.length,
            getFirstTextNode(textBlocks[4]),
            'remove'.length
        )
        fireEvent.keyDown(textBlocks[2], { key: 'Delete' })

        const nextTextBlocks = getEditableTextBlocks(container)
        expect(nextTextBlocks.map((block) => block.textContent)).toEqual([
            TEST_NOTEBOOK_TITLE,
            'Keep before',
            'Alpha  Omega',
            'Keep after',
        ])
        expect(document.activeElement).toEqual(nextTextBlocks[2])
        expect(window.getSelection()?.focusOffset).toEqual('Alpha '.length)
        expect(onChange).toHaveBeenLastCalledWith(
            `${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nKeep before\n\nAlpha  Omega\n\nKeep after`
        )
    })

    it('indents list items with tab while preserving selection', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`- Parent
- Child`),
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

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

- Parent
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
                value: withNotebookTitle(`| Name | Count |
| --- | --- |
| Pageview | 12 |`),
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

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

| Name | Count |
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
                value: withNotebookTitle(`| Name | Count |
| --- | --- |
| Pageview | 12 |`),
                onChange,
            })
        )
        const getCells = (): HTMLElement[] =>
            Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content')) as HTMLElement[]

        fireEvent.keyDown(getCells()[0], { key: 'Tab' })

        expect(document.activeElement).toEqual(getCells()[1])

        fireEvent.keyDown(getCells()[2], { key: 'Enter' })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

| Name | Count |
| --- | --- |
| Pageview | 12 |
|  |  |`)
        expect(document.activeElement).toEqual(getCells()[4])
    })

    it('adds and removes table rows and columns with controls', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`| Name | Count |
| --- | --- |
| Pageview | 12 |`),
                onChange,
            })
        )
        const getButton = (label: string): HTMLButtonElement => {
            const button = container.querySelector(`button[aria-label="${label}"]`)
            expect(button).toBeInstanceOf(HTMLButtonElement)
            return button as HTMLButtonElement
        }

        fireEvent.click(getButton('Add column after column 2'))

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

| Name | Count |  |
| --- | --- | --- |
| Pageview | 12 |  |`)
        expect(document.activeElement).toEqual(
            Array.from(container.querySelectorAll('.MarkdownNotebook__table-cell-content'))[2]
        )

        fireEvent.click(getButton('Remove column 3'))

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

| Name | Count |
| --- | --- |
| Pageview | 12 |`)

        fireEvent.click(getButton('Add row after row 1'))

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

| Name | Count |
| --- | --- |
| Pageview | 12 |
|  |  |`)

        fireEvent.click(getButton('Remove row 2'))

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

| Name | Count |
| --- | --- |
| Pageview | 12 |`)
    })

    it('pastes markdown tables as notebook table blocks', () => {
        const onChange = jest.fn()
        const pastedMarkdown = `| Name | Count |
| --- | ---: |
| Pageview | **12** |`
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(' '), onChange }))
        const textBlock = getBodyTextBlock(container)

        fireEvent.paste(textBlock, {
            clipboardData: {
                getData: jest.fn((type: string) => (type === 'text/plain' ? pastedMarkdown : '')),
            },
        })

        expect(container.querySelector('.MarkdownNotebook__table-block')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__table-cell-content')?.textContent).toEqual('Name')
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\n${pastedMarkdown}`)
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
        const textBlock = container.querySelector(NOTEBOOK_TEST_EDITABLE_SELECTOR)

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
        const { container } = render(createElement(MarkdownNotebook, { value: withNotebookTitle(markdown), onChange }))
        const trailingTextBlock = getEditableTextBlocks(container).at(-1)

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
                value: withNotebookTitle(`First paragraph

Second paragraph`),
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

        const textBlocks = getEditableTextBlocks(container)
        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}

First paragraph

Second paragraph

 `)
        expect(textBlocks).toHaveLength(4)
        expect(document.activeElement).toEqual(textBlocks[3])
        expect(window.getSelection()?.focusOffset).toEqual(0)
    })

    it('combines text blocks when pressing backspace at the start of a text block', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: withNotebookTitle(`First paragraph

Second paragraph`),
                onChange,
            })
        )
        const textBlocks = getEditableTextBlocks(container)

        selectTextInElement(textBlocks[2], 0, 0)
        fireEvent.keyDown(textBlocks[2], { key: 'Backspace' })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nFirst paragraphSecond paragraph`)
        expect(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)).toHaveLength(2)
        expect(document.activeElement?.textContent).toEqual('First paragraphSecond paragraph')
        expect(window.getSelection()?.focusOffset).toEqual('First paragraph'.length)
    })

    it('deletes an empty text row and moves the cursor to the previous text block on backspace', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, { value: withNotebookTitle('First paragraph'), onChange })
        )
        const firstTextBlock = getBodyTextBlock(container)

        selectTextInElement(firstTextBlock, 'First paragraph'.length, 'First paragraph'.length)
        fireEvent.keyDown(firstTextBlock, { key: 'Enter' })

        const textBlocks = getEditableTextBlocks(container)

        expect(textBlocks).toHaveLength(3)
        expect(document.activeElement).toEqual(textBlocks[2])

        fireEvent.keyDown(textBlocks[2], { key: 'Backspace' })

        expect(onChange).toHaveBeenLastCalledWith(`${TEST_NOTEBOOK_TITLE_MARKDOWN}\n\nFirst paragraph`)
        expect(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)).toHaveLength(2)
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
        const textBlocks = Array.from(container.querySelectorAll(NOTEBOOK_TEST_EDITABLE_SELECTOR)) as HTMLElement[]
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
