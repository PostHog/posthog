import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as React from 'react'

import { Tree, TreeItemLabel, type TreeNode, type TreeProps } from './tree'

interface Node extends TreeNode {
    children?: Node[]
}

const ITEMS: Node[] = [
    {
        id: 'fruit',
        textValue: 'Fruit',
        children: [
            { id: 'apple', textValue: 'Apple' },
            { id: 'banana', textValue: 'Banana' },
        ],
    },
    {
        id: 'veg',
        textValue: 'Vegetables',
        children: [{ id: 'carrot', textValue: 'Carrot' }],
    },
    { id: 'bread', textValue: 'Bread' },
    { id: 'lazy', textValue: 'Lazy', hasChildren: true },
]

type HarnessProps = Partial<TreeProps<Node>> & { initialExpanded?: string[] }

function Harness({ initialExpanded = [], items = ITEMS, ...props }: HarnessProps): JSX.Element {
    const [expandedIds, setExpandedIds] = React.useState(initialExpanded)
    const [selectedId, setSelectedId] = React.useState<string | null>(null)
    return (
        <Tree
            aria-label="Groceries"
            items={items}
            expandedIds={expandedIds}
            onExpandedIdsChange={setExpandedIds}
            selectedId={selectedId}
            onSelectedIdChange={setSelectedId}
            renderItem={(node) => <TreeItemLabel>{node.textValue}</TreeItemLabel>}
            {...props}
        />
    )
}

const row = (name: string): HTMLElement => screen.getByRole('treeitem', { name })
const focused = (): string | null => document.activeElement?.textContent ?? null

async function focusFirst(): Promise<void> {
    await userEvent.tab()
}

describe('Tree', () => {
    afterEach(() => cleanup())

    it('exposes the tree pattern aria attributes', () => {
        render(<Harness initialExpanded={['fruit']} />)

        expect(screen.getByRole('tree', { name: 'Groceries' })).toBeTruthy()
        const fruit = row('Fruit')
        expect(fruit.getAttribute('aria-level')).toBe('1')
        expect(fruit.getAttribute('aria-posinset')).toBe('1')
        expect(fruit.getAttribute('aria-setsize')).toBe('4')
        expect(fruit.getAttribute('aria-expanded')).toBe('true')
        expect(fruit.getAttribute('aria-selected')).toBe('false')
        expect(row('Vegetables').getAttribute('aria-expanded')).toBe('false')

        const banana = row('Banana')
        expect(banana.getAttribute('aria-level')).toBe('2')
        expect(banana.getAttribute('aria-posinset')).toBe('2')
        expect(banana.getAttribute('aria-setsize')).toBe('2')
        expect(banana.hasAttribute('aria-expanded')).toBe(false)
    })

    it('keeps exactly one row in the tab order', async () => {
        render(<Harness initialExpanded={['fruit']} />)
        const tabbable = (): HTMLElement[] =>
            screen.getAllByRole('treeitem').filter((element) => element.getAttribute('tabindex') === '0')

        expect(tabbable().map((element) => element.textContent)).toEqual(['Fruit'])
        await focusFirst()
        await userEvent.keyboard('{ArrowDown}{ArrowDown}')
        expect(tabbable().map((element) => element.textContent)).toEqual(['Banana'])
    })

    it('moves with the arrow keys, Home and End', async () => {
        render(<Harness initialExpanded={['fruit']} />)
        await focusFirst()
        expect(focused()).toBe('Fruit')

        await userEvent.keyboard('{ArrowDown}')
        expect(focused()).toBe('Apple')
        await userEvent.keyboard('{ArrowUp}')
        expect(focused()).toBe('Fruit')
        await userEvent.keyboard('{End}')
        expect(focused()).toBe('Lazy')
        await userEvent.keyboard('{Home}')
        expect(focused()).toBe('Fruit')
    })

    it('expands with Right, then steps into the first child', async () => {
        render(<Harness />)
        await focusFirst()

        await userEvent.keyboard('{ArrowRight}')
        expect(row('Fruit').getAttribute('aria-expanded')).toBe('true')
        expect(focused()).toBe('Fruit')

        await userEvent.keyboard('{ArrowRight}')
        expect(focused()).toBe('Apple')
    })

    it('collapses with Left, then steps to the parent', async () => {
        render(<Harness initialExpanded={['fruit']} />)
        await focusFirst()
        await userEvent.keyboard('{ArrowDown}{ArrowDown}')
        expect(focused()).toBe('Banana')

        await userEvent.keyboard('{ArrowLeft}')
        expect(focused()).toBe('Fruit')
        expect(row('Fruit').getAttribute('aria-expanded')).toBe('true')

        await userEvent.keyboard('{ArrowLeft}')
        expect(row('Fruit').getAttribute('aria-expanded')).toBe('false')
        expect(screen.queryByRole('treeitem', { name: 'Banana' })).toBeNull()
    })

    it('moves to the next row that starts with the typed text', async () => {
        render(<Harness initialExpanded={['fruit']} />)
        await focusFirst()

        await userEvent.keyboard('b')
        expect(focused()).toBe('Banana')
        await userEvent.keyboard('r')
        expect(focused()).toBe('Bread')
    })

    it('selects and calls onAction on Enter, and only selects on Space', async () => {
        const onAction = jest.fn()
        render(<Harness onAction={onAction} />)
        await focusFirst()
        await userEvent.keyboard('{End}{ArrowUp}')
        expect(focused()).toBe('Bread')

        await userEvent.keyboard(' ')
        expect(row('Bread').getAttribute('aria-selected')).toBe('true')
        expect(onAction).not.toHaveBeenCalled()

        await userEvent.keyboard('{Enter}')
        expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ id: 'bread' }))
    })

    it('expands every sibling with *', async () => {
        const onLoadChildren = jest.fn()
        render(<Harness onLoadChildren={onLoadChildren} />)
        await focusFirst()

        await userEvent.keyboard('*')

        expect(row('Fruit').getAttribute('aria-expanded')).toBe('true')
        expect(row('Vegetables').getAttribute('aria-expanded')).toBe('true')
        expect(row('Lazy').getAttribute('aria-expanded')).toBe('true')
        expect(onLoadChildren).toHaveBeenCalledTimes(1)
    })

    it('loads children when a node with unloaded children expands', async () => {
        const onLoadChildren = jest.fn()
        render(<Harness onLoadChildren={onLoadChildren} />)

        await userEvent.click(row('Lazy'))

        expect(onLoadChildren).toHaveBeenCalledWith(expect.objectContaining({ id: 'lazy' }))
        expect(row('Lazy').getAttribute('aria-expanded')).toBe('true')
        expect(row('Lazy').getAttribute('aria-busy')).toBe('true')
    })

    it('toggles a branch on click and runs the action on a leaf', async () => {
        const onAction = jest.fn()
        render(<Harness onAction={onAction} />)

        await userEvent.click(row('Fruit'))
        expect(row('Fruit').getAttribute('aria-expanded')).toBe('true')
        expect(onAction).not.toHaveBeenCalled()

        await userEvent.click(row('Apple'))
        expect(row('Apple').getAttribute('aria-selected')).toBe('true')
        expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ id: 'apple' }))
    })

    it('renders only a window of rows when virtualized', async () => {
        const items: Node[] = Array.from({ length: 5000 }, (_, index) => ({
            id: `row-${index}`,
            textValue: `Row ${index}`,
        }))
        render(<Harness items={items} virtualized overscan={10} />)

        const rendered = screen.getAllByRole('treeitem')
        expect(rendered.length).toBeGreaterThan(0)
        expect(rendered.length).toBeLessThan(100)

        // The focused row stays rendered when it leaves the window.
        await focusFirst()
        await userEvent.keyboard('{End}')
        expect(focused()).toBe('Row 4999')
        expect(row('Row 4999').getAttribute('aria-posinset')).toBe('5000')
    })

    it('renders the empty content when there are no items', () => {
        render(<Harness items={[]} empty={<span>Nothing here</span>} />)

        expect(screen.getByText('Nothing here')).toBeTruthy()
        expect(screen.queryByRole('treeitem')).toBeNull()
    })
})
