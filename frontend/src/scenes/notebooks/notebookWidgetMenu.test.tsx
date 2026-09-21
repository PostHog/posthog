import type { MouseEvent } from 'react'

import { getNotebookWidgetViewMenuItem } from './notebookWidgetMenu'

describe('getNotebookWidgetViewMenuItem', () => {
    it('lists every exported view, marks the active view, and stores the canonical default view', () => {
        const updateAttributes = jest.fn()
        const menuItem = getNotebookWidgetViewMenuItem(
            {
                defaultView: { key: 'detail', label: 'Detail' },
                views: {
                    summary: { label: 'Summary', Component: () => null },
                    results: { label: 'Results', Component: () => null },
                },
            },
            { nodeId: 'experiment-node', view: 'summary' },
            updateAttributes
        )

        expect(menuItem).toMatchObject({
            label: 'Change view',
            closeOnClickInside: false,
            closeParentPopoverOnClickInside: false,
        })
        if (!menuItem || !('items' in menuItem) || !Array.isArray(menuItem.items)) {
            throw new Error('Expected a nested view menu')
        }

        expect(menuItem.items).toMatchObject([
            { label: 'Detail', active: false },
            { label: 'Summary', active: true },
            { label: 'Results', active: false },
        ])
        expect(menuItem.items.every((item) => !item || !('sideIcon' in item) || item.sideIcon === undefined)).toBe(true)

        const detailItem = menuItem.items[0]
        if (!detailItem || !('onClick' in detailItem) || !detailItem.onClick) {
            throw new Error('Expected the detail view action')
        }
        detailItem.onClick({} as MouseEvent)
        expect(updateAttributes).toHaveBeenCalledWith({ view: 'detail' })
    })
})
