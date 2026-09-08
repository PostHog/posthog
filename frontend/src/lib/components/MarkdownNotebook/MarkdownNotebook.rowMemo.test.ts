import { act, fireEvent, render } from '@testing-library/react'
import { createElement, type ChangeEvent } from 'react'

// Monaco cannot run in jsdom; stand in with a plain textarea that honors value/onChange.
jest.mock('lib/monaco/CodeEditor', () => {
    // oxlint-disable-next-line no-require-imports
    const react = require('react') as typeof import('react')
    return {
        CodeEditor: ({ value, onChange }: { value?: string; onChange?: (value: string | undefined) => void }) =>
            react.createElement('textarea', {
                'data-attr': 'mock-code-editor',
                value: value ?? '',
                onChange: (event: ChangeEvent<HTMLTextAreaElement>) => onChange?.(event.target.value),
            }),
    }
})

// renderNode runs once per row that actually re-renders: the editor memoizes each row and reuses
// its element while the row's inputs are unchanged, so a reused row never reaches renderNode. Wrap
// the real implementation in a spy to count, per row, how many rows re-render after an interaction.
jest.mock('./renderNode', () => {
    const actual = jest.requireActual('./renderNode')
    return {
        __esModule: true,
        ...actual,
        renderNode: jest.fn(actual.renderNode),
    }
})

import { MarkdownNotebook } from './MarkdownNotebook'
import { renderNode } from './renderNode'

const renderNodeMock = renderNode as jest.MockedFunction<typeof renderNode>

function reRenderedRowIndexes(): number[] {
    return renderNodeMock.mock.calls.map(([props]) => props.nodeIndex)
}

function stubRowRect(row: Element, top: number, height: number): void {
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

describe('MarkdownNotebook row memoization', () => {
    beforeEach(() => {
        renderNodeMock.mockClear()
    })

    it('re-renders only the hovered row, not the whole notebook, on a hover', () => {
        const { container } = render(
            createElement(MarkdownNotebook, { value: '# Title\n\nalpha\n\nbravo\n\ncharlie\n\ndelta' })
        )
        const rows = Array.from(container.querySelectorAll('.MarkdownNotebook__row'))
        // title (0), alpha (1), bravo (2), charlie (3), delta (4)
        expect(rows).toHaveLength(5)
        rows.forEach((row, index) => stubRowRect(row, index * 100, 100))

        renderNodeMock.mockClear()

        // Hovering a middle row shows that row's inline insert button, so that row re-renders.
        fireEvent.mouseEnter(rows[2], { clientY: 220 })

        const reRendered = reRenderedRowIndexes()
        // The hovered row re-rendered to reveal its insert button.
        expect(reRendered).toContain(2)
        // The other rows kept their inputs, so they were reused, not re-rendered with the hover.
        expect(reRendered).not.toContain(0)
        expect(reRendered).not.toContain(4)
    })

    it('shows the insert boundary again when hovering after a focused row blurs', () => {
        // A reused row keeps its cached hover handlers, so the boundary suppression they apply
        // while a row is focused must come from current state — a handler that closed over the
        // focused-state of an earlier render would keep suppressing the boundary after blur.
        const { container } = render(createElement(MarkdownNotebook, { value: '# Title\n\nalpha\n\nbravo\n\ncharlie' }))
        const rows = Array.from(container.querySelectorAll('.MarkdownNotebook__row'))
        rows.forEach((row, index) => stubRowRect(row, index * 100, 100))
        const visibleBoundaries = (): number =>
            container.querySelectorAll('.MarkdownNotebook__insert-boundary-button--visible').length

        fireEvent.mouseEnter(rows[2], { clientY: 220 })
        expect(visibleBoundaries()).toBeGreaterThan(0)

        const alpha = container.querySelectorAll(
            '.MarkdownNotebook__text-block[contenteditable="true"]'
        )[1] as HTMLElement
        act(() => alpha.focus())
        fireEvent.mouseMove(rows[2], { clientY: 220 })
        expect(visibleBoundaries()).toBe(0)

        // Hover the same row after blur: it last re-rendered while the focus was active, so its
        // cached handlers are the ones that would hold a stale focused state.
        act(() => alpha.blur())
        fireEvent.mouseMove(rows[2], { clientY: 220 })
        expect(visibleBoundaries()).toBeGreaterThan(0)
    })

    it('re-renders only the edited row, not the unchanged title or a distant row', () => {
        const { container } = render(createElement(MarkdownNotebook, { value: '# Title\n\nalpha\n\nbravo\n\ncharlie' }))
        const textBlocks = Array.from(
            container.querySelectorAll('.MarkdownNotebook__text-block[contenteditable="true"]')
        ) as HTMLElement[]
        // title (0), alpha (1), bravo (2), charlie (3)
        expect(textBlocks).toHaveLength(4)

        renderNodeMock.mockClear()

        const alpha = textBlocks[1]
        act(() => {
            alpha.focus()
            alpha.textContent = 'alpha edited'
        })
        fireEvent.input(alpha)

        const reRendered = reRenderedRowIndexes()
        // The edited row re-rendered, so the change is not dropped.
        expect(reRendered).toContain(1)
        // Its object reference is unchanged, so the title and a distant row are reused, not re-rendered.
        expect(reRendered).not.toContain(0)
        expect(reRendered).not.toContain(3)
    })
})
