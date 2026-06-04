import { act, fireEvent, render } from '@testing-library/react'
import { createElement, useEffect } from 'react'

import { mergeNotebookMarkdownChanges } from './collaboration'
import {
    htmlElementToInlineNodes,
    parseMarkdownNotebook,
    serializeInlineNodes,
    serializeMarkdownNotebook,
} from './markdown'
import { MarkdownNotebook } from './MarkdownNotebook'
import { reconcileNotebookDocuments } from './reconcile'
import { createMarkdownNotebookRegistry } from './registry'

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
        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph')
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
        expect(slashTextBlock.getAttribute('data-placeholder')).toEqual('Search for tool')

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
        expect(onChange).toHaveBeenLastCalledWith('Intro paragraph')
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

    it('only reveals boundary add buttons around the active populated row', () => {
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph

Third paragraph`,
            })
        )
        const canvas = container.querySelector('.MarkdownNotebook__canvas')
        const rows = Array.from(container.querySelectorAll('.MarkdownNotebook__row'))
        const getVisibleBoundaryIndexes = (): string[] =>
            Array.from(container.querySelectorAll('.MarkdownNotebook__insert-boundary-button--visible')).map(
                (button) => (button as HTMLElement).dataset.boundaryIndex ?? ''
            )

        expect(canvas).toBeInstanceOf(HTMLElement)
        expect(rows).toHaveLength(3)
        expect(getVisibleBoundaryIndexes()).toEqual([])

        fireEvent.mouseEnter(rows[1])
        expect(getVisibleBoundaryIndexes()).toEqual(['1', '2'])

        fireEvent.mouseEnter(rows[0])
        expect(getVisibleBoundaryIndexes()).toEqual(['0', '1'])

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
        expect(container.querySelector('[data-placeholder="Search for tool"]')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('[data-placeholder="Start writing..."]')).toBeNull()
        expect(document.activeElement).toEqual(editableTextBlock)

        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()
        expect(container.querySelector('[data-placeholder="Start writing..."]')).toBeInstanceOf(HTMLElement)
        expect(document.activeElement).toEqual(editableTextBlock)

        fireEvent.click(container.querySelector('.MarkdownNotebook__line-insert-menu-button') as HTMLButtonElement)

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('[data-placeholder="Search for tool"]')).toBeInstanceOf(HTMLElement)

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

        fireEvent.keyDown(editableTextBlock, { key: 'Enter' })

        expect(container.querySelector('.MarkdownNotebook__insert-menu')).toBeNull()
        expect(onChange).toHaveBeenLastCalledWith(expect.stringContaining('TrendsQuery'))
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

        expect(onChange).toHaveBeenLastCalledWith('\n\nIntro paragraph')
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

    it('deletes the block above when pressing backspace at the start of a text block', () => {
        const onChange = jest.fn()
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second paragraph`,
                onChange,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const secondTextNode = textBlocks[1].firstChild

        expect(secondTextNode).toBeInstanceOf(Text)

        act(() => {
            const range = document.createRange()
            range.setStart(secondTextNode as Text, 0)
            range.setEnd(secondTextNode as Text, 0)
            const selection = window.getSelection()
            selection?.removeAllRanges()
            selection?.addRange(range)
        })
        fireEvent.keyDown(textBlocks[1], { key: 'Backspace' })

        expect(onChange).toHaveBeenLastCalledWith('Second paragraph')
    })

    it('moves focus between notebook rows with arrow keys while retaining cursor offset', () => {
        const { container } = render(
            createElement(MarkdownNotebook, {
                value: `First paragraph

Second

<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />`,
            })
        )
        const textBlocks = Array.from(container.querySelectorAll('[contenteditable="true"]')) as HTMLElement[]
        const firstTextNode = textBlocks[0].firstChild
        const secondTextNode = textBlocks[1].firstChild

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

        expect(document.activeElement).toEqual(container.querySelector('.MarkdownNotebook__component-shell'))
    })

    it('toggles component edit and view panels independently with edit above view', () => {
        const markdown = `<Query query={{"kind":"DataTableNode","source":{"kind":"EventsQuery"}}} />`
        const { container } = render(createElement(MarkdownNotebook, { value: markdown }))
        const shell = container.querySelector('.MarkdownNotebook__component-shell')
        const actionButtons = Array.from(
            container.querySelectorAll('.MarkdownNotebook__component-actions button')
        ) as HTMLButtonElement[]

        expect(shell).toBeInstanceOf(HTMLElement)
        expect(actionButtons).toHaveLength(3)
        expect(container.querySelector('.MarkdownNotebook__component-preview')).toBeInstanceOf(HTMLElement)
        expect(container.querySelector('.MarkdownNotebook__component-edit')).toBeNull()

        fireEvent.click(actionButtons[0])

        const stackedPanels = Array.from(shell?.querySelectorAll('.MarkdownNotebook__component-panel') ?? [])
        expect(stackedPanels).toHaveLength(2)
        expect(stackedPanels[0].querySelector('.MarkdownNotebook__component-edit')).toBeInstanceOf(HTMLElement)
        expect(stackedPanels[1].querySelector('.MarkdownNotebook__component-preview')).toBeInstanceOf(HTMLElement)

        fireEvent.click(actionButtons[1])

        expect(container.querySelector('.MarkdownNotebook__component-preview')).toBeNull()
        expect(container.querySelector('.MarkdownNotebook__component-edit')).toBeInstanceOf(HTMLElement)
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
