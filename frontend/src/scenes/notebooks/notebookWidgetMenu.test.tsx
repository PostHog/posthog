import type { MouseEvent } from 'react'

import { getNotebookWidgetViewMenuItem } from './notebookWidgetMenu'

describe('getNotebookWidgetViewMenuItem', () => {
    it('lists every exported view and stores the default view without an attribute', () => {
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

        expect(menuItem).toMatchObject({ label: 'Change view' })
        if (!menuItem || !('items' in menuItem) || !Array.isArray(menuItem.items)) {
            throw new Error('Expected a nested view menu')
        }

        expect(menuItem.items).toMatchObject([
            { label: 'Detail', active: false },
            { label: 'Summary', active: true },
            { label: 'Results', active: false },
        ])

        const detailItem = menuItem.items[0]
        if (!detailItem || !('onClick' in detailItem) || !detailItem.onClick) {
            throw new Error('Expected the detail view action')
        }
        detailItem.onClick({} as MouseEvent)
        expect(updateAttributes).toHaveBeenCalledWith({ view: undefined })
    })
})
