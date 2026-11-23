import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'
import { cloneElement } from 'react'

import { makeTraceResource } from '../testFixtures'
import { TraceTree, TraceTreeProps } from './TraceTree'

function renderTree(props: Partial<TraceTreeProps> = {}): ReturnType<typeof render> & { tree: JSX.Element } {
    const tree = (
        <TraceTree
            nodes={makeTraceResource().tree}
            selectedNodeId="span-1"
            onSelectNode={() => {}}
            onStepNode={() => {}}
            onPrefetchNode={() => {}}
            evalOutcomes={new Map()}
            {...props}
        />
    )
    return { ...render(tree), tree }
}

function rows(container: HTMLElement): HTMLElement[] {
    return [...container.querySelectorAll<HTMLElement>('[data-attr="trace-view-tree-node"]')]
}

function rowOf(container: HTMLElement, name: string): HTMLElement {
    const row = rows(container).find((button) => button.textContent?.includes(name))
    if (!row) {
        throw new Error(`No tree row named ${name}`)
    }
    return row
}

describe('TraceTree', () => {
    it.each(['constructor', 'toString', '__proto__'])(
        'renders a step whose id %s names an object property without an eval marker',
        (id) => {
            const [root] = makeTraceResource().tree
            const { getByText, queryByLabelText } = renderTree({
                nodes: [{ ...root, id, name: id, children: [] }],
                selectedNodeId: null,
            })

            expect(getByText(id)).toBeInTheDocument()
            expect(queryByLabelText(/^Evals/)).toBeNull()
        }
    )

    it.each([
        ['ArrowDown', {}, ['next']],
        ['ArrowUp', {}, ['previous']],
        ['ArrowLeft', {}, ['parent']],
        ['ArrowRight', {}, ['child']],
        ['Home', {}, ['first']],
        ['End', {}, ['last']],
        ['ArrowDown', { shiftKey: true }, []],
        ['Enter', {}, []],
    ] as const)('%s with %j on a row steps %j', (key, modifiers, expected) => {
        const onStepNode = jest.fn()
        const { container } = renderTree({ onStepNode })

        const notPrevented = fireEvent.keyDown(rowOf(container, 'span-1'), { key, ...modifiers })

        expect(onStepNode.mock.calls.flat()).toEqual(expected)
        expect(notPrevented).toBe(expected.length === 0)
    })

    it('exposes a tree whose rows carry their level, their place among siblings and the selection', () => {
        const { container } = renderTree()

        expect(container.querySelector('[role="tree"]')).toHaveAccessibleName('Trace steps')
        expect(
            rows(container).map((row) =>
                ['role', 'aria-level', 'aria-posinset', 'aria-setsize', 'aria-selected']
                    .map((name) => row.getAttribute(name))
                    .join(' ')
            )
        ).toEqual(['treeitem 1 1 1 false', 'treeitem 2 1 3 true', 'treeitem 2 2 3 false', 'treeitem 2 3 3 false'])

        const [root, ...children] = rows(container)
        const group = container.querySelector('[role="group"]')
        expect(root).toHaveAttribute('aria-expanded', 'true')
        expect(root.getAttribute('aria-owns')).toBe(group?.id)
        expect(children.every((row) => group?.contains(row))).toBe(true)
        expect(children.some((row) => row.hasAttribute('aria-expanded') || row.hasAttribute('aria-owns'))).toBe(false)
    })

    it.each([
        ['span-1', 'span-1'],
        ['not-a-step', 'answer-billing-question'],
        [null, 'answer-billing-question'],
    ])('with %s selected, Tab lands only on %s', (selectedNodeId, expected) => {
        const { container } = renderTree({ selectedNodeId })

        expect(rows(container).filter((row) => row.tabIndex === 0)).toEqual([rowOf(container, expected)])
    })

    it('moves focus with the selection only from inside the tree, without prefetching, and announces a step that takes no focus', () => {
        const onPrefetchNode = jest.fn()
        const { container, rerender, tree } = renderTree({ onPrefetchNode })
        const announcement = container.querySelector('[aria-live="polite"]')

        rerender(cloneElement(tree, { selectedNodeId: 'gen-1', revealCount: 1 }))
        expect(container.contains(document.activeElement)).toBe(false)
        expect(announcement).toHaveTextContent('gen-1, step 3 of 4')

        rowOf(container, 'gen-1').focus()
        rerender(cloneElement(tree, { selectedNodeId: 'gen-2', revealCount: 2 }))
        expect(document.activeElement).toBe(rowOf(container, 'gen-2'))
        expect(announcement).toHaveTextContent('gen-1, step 3 of 4')
        expect(onPrefetchNode).not.toHaveBeenCalled()
    })

    it.each([
        [true, 'traces'],
        [false, null],
    ])('names the trace keys in its legend only where they work (%s)', (showTraceKeys, expected) => {
        const { container } = renderTree({ showTraceKeys })
        const legend = container.querySelector('[data-attr="trace-view-tree-key-legend"]')

        expect(legend).toHaveTextContent('steps')
        expect(legend?.textContent?.match(/traces/)?.[0] ?? null).toBe(expected)
    })
})
