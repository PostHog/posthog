import { act, fireEvent, render } from '@testing-library/react'
import { createElement, useCallback } from 'react'

import { usePublishNotebookComponentRunHandler } from './componentRunHandlers'
import { MarkdownNotebookJupyterModeConfig, NotebookJupyterCommands, useNotebookJupyterCommands } from './jupyterMode'
import { MarkdownNotebook } from './MarkdownNotebook'
import { createMarkdownNotebookRegistry } from './registry'
import type { NotebookComponentRenderProps, NotebookComponentToolbarProps } from './types'

const runs: string[] = []

function RunPublisher({ node }: NotebookComponentToolbarProps): null {
    const code = String(node.props.code)
    const run = useCallback(() => runs.push(code), [code])
    usePublishNotebookComponentRunHandler({ run })
    return null
}

// Monaco cannot run in jsdom; a textarea inside `.monaco-editor` is what the cell treats as its editor.
function CodeEditorStandIn({ node }: NotebookComponentRenderProps): JSX.Element {
    return createElement(
        'div',
        { className: 'monaco-editor' },
        createElement('textarea', { 'data-attr': 'cell-editor', defaultValue: String(node.props.code ?? '') })
    )
}

const registry = createMarkdownNotebookRegistry([
    {
        tagName: 'Py',
        label: 'Python',
        category: 'Code',
        defaultProps: { code: '' },
        ViewComponent: () => createElement('div', null, 'output'),
        EditComponent: CodeEditorStandIn,
        ToolbarComponent: RunPublisher,
    },
])

const jupyterMode: MarkdownNotebookJupyterModeConfig = {
    cellTagNames: ['Py'],
    newCellTagName: 'Py',
    getCellSource: (node) => String(node.props.code ?? ''),
    withCellSource: (node, source) => ({ ...node, props: { ...node.props, code: source } }),
}

let commands: NotebookJupyterCommands | null = null
function CommandsProbe(): null {
    commands = useNotebookJupyterCommands()
    return null
}

function renderJupyterNotebook(markdown: string): {
    container: HTMLElement
    latest: () => string
    cell: (index: number) => HTMLElement
    editor: (index: number) => HTMLTextAreaElement
    sink: () => HTMLElement
} {
    runs.length = 0
    const onChange = jest.fn()
    const { container } = render(
        createElement(MarkdownNotebook, {
            value: markdown,
            onChange,
            registry,
            jupyterMode,
            canvasHeader: createElement(CommandsProbe),
        })
    )
    const cell = (index: number): HTMLElement =>
        container.querySelectorAll<HTMLElement>('[data-attr="notebook-jupyter-cell"]')[index]
    return {
        container,
        latest: () => (onChange.mock.calls.at(-1)?.[0] as string | undefined) ?? markdown,
        cell,
        editor: (index) => cell(index).querySelector('[data-attr="cell-editor"]') as HTMLTextAreaElement,
        sink: () => container.querySelector('[data-attr="notebook-jupyter-command-sink"]') as HTMLElement,
    }
}

function press(element: HTMLElement, key: string, modifiers: Partial<KeyboardEventInit> = {}): void {
    act(() => {
        fireEvent.keyDown(element, { key, ...modifiers })
    })
}

// requestAnimationFrame-deferred focus moves run before the next assertion.
async function flushFrames(): Promise<void> {
    await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50))
    })
}

const TWO_CELLS = '# Title\n\nIntro\n\n<Py code="a = 1" />\n\n<Py code="b = 2" />'

describe('MarkdownNotebook in Jupyter mode', () => {
    it.each([
        [
            'A inserts a cell above',
            ['a'],
            '# Title\n\nIntro\n\n<Py code="" />\n\n<Py code="a = 1" />\n\n<Py code="b = 2" />',
        ],
        [
            'B inserts a cell below',
            ['b'],
            '# Title\n\nIntro\n\n<Py code="a = 1" />\n\n<Py code="" />\n\n<Py code="b = 2" />',
        ],
        ['D, D deletes the cell', ['d', 'd'], '# Title\n\nIntro\n\n<Py code="b = 2" />'],
        ['Delete deletes the cell', ['Delete'], '# Title\n\nIntro\n\n<Py code="b = 2" />'],
        ['D, D then Z restores the cell', ['d', 'd', 'z'], TWO_CELLS],
        [
            'C then V pastes a copy below',
            ['c', 'v'],
            '# Title\n\nIntro\n\n<Py code="a = 1" />\n\n<Py code="a = 1" />\n\n<Py code="b = 2" />',
        ],
        ['M turns the code into markdown', ['m'], '# Title\n\nIntro\n\n\na = 1\n\n<Py code="b = 2" />'],
        ['Shift+M merges with the cell below', ['M+shift'], '# Title\n\nIntro\n\n<Py code="a = 1\\n\\nb = 2" />'],
        [
            'Cmd+Shift+Down moves the cell down',
            ['ArrowDown+meta+shift'],
            '# Title\n\nIntro\n\n<Py code="b = 2" />\n\n<Py code="a = 1" />',
        ],
    ])('%s', async (_, keys, expected) => {
        const notebook = renderJupyterNotebook(TWO_CELLS)
        act(() => notebook.cell(0).focus())
        for (const combo of keys) {
            const [key, ...modifiers] = combo.split('+')
            press(document.activeElement as HTMLElement, key, {
                shiftKey: modifiers.includes('shift'),
                metaKey: modifiers.includes('meta'),
            })
            await flushFrames()
        }
        expect(notebook.latest()).toEqual(expected)
    })

    it('keeps a markdown cell whole when a code cell moves up past it', async () => {
        const notebook = renderJupyterNotebook(
            '# Title\n\nIntro\n\n<Py code="a = 1" />\n\n\nOne\n\nTwo\n\n<Py code="b = 2" />'
        )
        act(() => notebook.cell(1).focus())
        press(notebook.cell(1), 'ArrowUp', { shiftKey: true, metaKey: true })
        await flushFrames()
        expect(notebook.latest()).toEqual(
            '# Title\n\nIntro\n\n<Py code="a = 1" />\n\n<Py code="b = 2" />\n\n\nOne\n\nTwo'
        )
    })

    it('never turns keys typed in a code editor into cell commands', () => {
        const notebook = renderJupyterNotebook(TWO_CELLS)
        for (const key of ['a', 'b', 'd', 'd', 'm', 'Delete', 'Backspace']) {
            press(notebook.editor(0), key)
        }
        expect(notebook.latest()).toEqual(TWO_CELLS)
    })

    it('runs with Shift+Enter, selects the next cell, and adds a cell after the last one', async () => {
        const notebook = renderJupyterNotebook(TWO_CELLS)
        press(notebook.editor(0), 'Enter', { shiftKey: true })
        await flushFrames()
        expect(runs).toEqual(['a = 1'])
        expect(document.activeElement).toBe(notebook.cell(1))

        press(notebook.cell(1), 'Enter', { shiftKey: true })
        await flushFrames()
        expect(runs).toEqual(['a = 1', 'b = 2'])
        expect(notebook.latest()).toEqual(`${TWO_CELLS}\n\n<Py code="" />`)
    })

    it('selects a markdown cell in command mode, where letter keys act on it instead of typing', async () => {
        const notebook = renderJupyterNotebook(TWO_CELLS)
        act(() => notebook.cell(0).focus())
        press(notebook.cell(0), 'k')
        await flushFrames()
        expect(document.activeElement).toBe(notebook.sink())

        // Y turns the markdown cell into code; the title row stays text.
        press(notebook.sink(), 'y')
        await flushFrames()
        expect(notebook.latest()).toEqual(
            '# Title\n\n<Py code="Intro" />\n\n<Py code="a = 1" />\n\n<Py code="b = 2" />'
        )
    })

    it('leaves markdown edit mode with Escape and adds a code cell below with B', async () => {
        const notebook = renderJupyterNotebook(TWO_CELLS)
        const intro = [...notebook.container.querySelectorAll<HTMLElement>('[data-markdown-notebook-node-id]')].find(
            (element) => element.textContent === 'Intro'
        )!
        act(() => {
            intro.focus()
            const range = document.createRange()
            range.setStart(intro.firstChild ?? intro, 0)
            window.getSelection()?.removeAllRanges()
            window.getSelection()?.addRange(range)
        })
        const canvas = notebook.container.querySelector('.MarkdownNotebook__canvas') as HTMLElement
        press(canvas, 'Escape')
        await flushFrames()
        expect(document.activeElement).toBe(notebook.sink())

        press(notebook.sink(), 'b')
        await flushFrames()
        expect(notebook.latest()).toEqual(
            '# Title\n\nIntro\n\n<Py code="" />\n\n<Py code="a = 1" />\n\n<Py code="b = 2" />'
        )
    })

    it('deletes every cell picked with Shift+Down', async () => {
        const notebook = renderJupyterNotebook(`${TWO_CELLS}\n\n<Py code="c = 3" />`)
        act(() => notebook.cell(0).focus())
        press(notebook.cell(0), 'ArrowDown', { shiftKey: true })
        press(document.activeElement as HTMLElement, 'd')
        press(document.activeElement as HTMLElement, 'd')
        await flushFrames()
        expect(notebook.latest()).toEqual('# Title\n\nIntro\n\n<Py code="c = 3" />')
    })

    it('splits a code cell at an offset into two cells, keeping the cell type', () => {
        const notebook = renderJupyterNotebook(TWO_CELLS)
        act(() => notebook.cell(0).focus())
        act(() => commands!.splitCell(commands!.store.getState().activeCellId!, 'a = 1'.length))
        expect(notebook.latest()).toEqual(
            '# Title\n\nIntro\n\n<Py code="a = 1" />\n\n<Py code="" />\n\n<Py code="b = 2" />'
        )
    })

    it('removes a cell emptied in its editor and edits the end of the cell above', async () => {
        const notebook = renderJupyterNotebook('# Title\n\nIntro\n\n<Py code="a = 1" />\n\n<Py code="" />')
        act(() => notebook.cell(1).focus())
        act(() => commands!.deleteEmptyCell(commands!.store.getState().activeCellId!))
        await flushFrames()
        expect(notebook.latest()).toEqual('# Title\n\nIntro\n\n<Py code="a = 1" />')
    })
})
