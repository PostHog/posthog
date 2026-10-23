import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biDrilldownLogic } from './biDrilldownLogic'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

const config = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'orders' },
    rows: [
        { id: 'status', name: 'Status', expression: 'status', type: 'string' as const, source: { table: 'orders' } },
    ],
}
const query: BIVisualizationNode = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }

describe('dashboard result exploration', () => {
    beforeEach(() => initKeaTests())

    it.each([{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }])(
        'leaves modified link clicks to the browser: %j',
        (modifiers) => {
            const onFilterDashboard = jest.fn()
            const logic = biDrilldownLogic({ key: 'modified', query, onFilterDashboard })
            const unmount = logic.mount()
            try {
                logic.actions.setInteraction({ x: 20, y: 30, clickCount: 1, timestamp: 100 })
                logic.actions.inspect({ status: 'paid' })
                const click = new MouseEvent('click', {
                    clientX: 20,
                    clientY: 30,
                    detail: 1,
                    cancelable: true,
                    ...modifiers,
                })
                Object.defineProperty(click, 'timeStamp', { value: 200 })
                document.dispatchEvent(click)
                expect(click.defaultPrevented).toBe(false)
                expect(onFilterDashboard).not.toHaveBeenCalled()
            } finally {
                unmount()
            }
        }
    )

    it('recognizes the second click when an edge-clamped menu covers the original chart target', () => {
        const onFilterDashboard = jest.fn()
        const logic = biDrilldownLogic({ key: 'edge', query, onFilterDashboard })
        const unmount = logic.mount()
        try {
            logic.actions.setInteraction({ x: 20, y: 30, clickCount: 1, timestamp: 100 })
            logic.actions.inspect({ status: 'paid' })
            const secondClick = new MouseEvent('click', { clientX: 20, clientY: 30, detail: 1, cancelable: true })
            Object.defineProperty(secondClick, 'timeStamp', { value: 200 })
            document.dispatchEvent(secondClick)
            expect(secondClick.defaultPrevented).toBe(true)
            expect(onFilterDashboard).toHaveBeenCalledTimes(1)
            expect(onFilterDashboard).toHaveBeenCalledWith({ status: 'paid' })
            expect(logic.values.record).toBeNull()
            logic.actions.inspect({ status: 'refunded' })
            expect(onFilterDashboard).toHaveBeenCalledTimes(1)
            expect(logic.values.record).toEqual({ status: 'refunded' })
            document.dispatchEvent(secondClick)
            expect(onFilterDashboard).toHaveBeenCalledTimes(1)
        } finally {
            unmount()
        }
    })

    it.each([1, 2])('filters once through the menu or a double-click (click count %s)', (clickCount) => {
        const onFilterDashboard = jest.fn()
        const logic = biDrilldownLogic({ key: 'orders', query, onFilterDashboard })
        const unmount = logic.mount()
        try {
            logic.actions.setInteraction({ x: 300, y: 250, clickCount })
            logic.actions.inspect({ status: 'paid' })
            if (clickCount === 1) {
                expect(onFilterDashboard).not.toHaveBeenCalled()
                expect(logic.values.selection?.labels).toEqual([{ name: 'Status', value: 'paid' }])
                logic.actions.filterDashboard()
            }
            expect(onFilterDashboard).toHaveBeenCalledTimes(1)
            expect(onFilterDashboard).toHaveBeenCalledWith({ status: 'paid' })
            expect(logic.values.record).toBeNull()
            logic.actions.inspect({ status: 'refunded' })
            expect(onFilterDashboard).toHaveBeenCalledTimes(1)
            expect(logic.values.record).toEqual({ status: 'refunded' })
        } finally {
            unmount()
        }
    })

    it('selects adjacent points directly while filtering, but still explores unsupported results', () => {
        const onFilterDashboard = jest.fn()
        const logic = biDrilldownLogic({ key: 'active', query, onFilterDashboard, dashboardFilterActive: true })
        const unmount = logic.mount()
        try {
            for (const status of ['paid', 'refunded', 'refunded']) {
                logic.actions.setInteraction({ x: 300, y: 250, clickCount: 1 })
                logic.actions.inspect({ status })
                expect(onFilterDashboard).toHaveBeenLastCalledWith({ status })
                expect(logic.values.record).toBeNull()
            }
            expect(onFilterDashboard).toHaveBeenCalledTimes(3)
            logic.actions.setInteraction({ x: 300, y: 250, clickCount: 1 })
            logic.actions.inspect({ count: 8 })
            expect(onFilterDashboard).toHaveBeenCalledTimes(3)
            expect(logic.values.record).toEqual({ count: 8 })
        } finally {
            unmount()
        }
    })

    it.each([{ count: 8 }, { status: 'paid', bi_comparison: 'Previous period' }])(
        'closes unsupported results without filtering on a second click: %j',
        (record) => {
            const onFilterDashboard = jest.fn()
            const logic = biDrilldownLogic({ key: 'unsupported', query, onFilterDashboard })
            const unmount = logic.mount()
            try {
                logic.actions.setInteraction({ x: 300, y: 250, clickCount: 2 })
                logic.actions.inspect(record)
                logic.actions.filterDashboard()
                expect(onFilterDashboard).not.toHaveBeenCalled()
                expect(logic.values.dashboardFilterDisabledReason).toBeTruthy()
                expect(logic.values.record).toBeNull()
                logic.actions.setInteraction({ x: 300, y: 250, clickCount: 1 })
                logic.actions.inspect(record)
                expect(logic.values.queries?.rows).toBeTruthy()
                logic.actions.viewRows()
                window.dispatchEvent(new Event('scroll'))
                expect(logic.values.showRows).toBe(true)
            } finally {
                unmount()
            }
        }
    )
})
