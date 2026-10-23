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

    it.each([1, 2])('opens the menu before filtering (click count %s)', (clickCount) => {
        const onFilterDashboard = jest.fn()
        const logic = biDrilldownLogic({ key: 'orders', query, onFilterDashboard })
        const unmount = logic.mount()
        try {
            logic.actions.setInteraction({ x: 300, y: 250, clickCount })
            logic.actions.inspect({ status: 'paid' })
            expect(onFilterDashboard).not.toHaveBeenCalled()
            expect(logic.values.selection?.labels).toEqual([{ name: 'Status', value: 'paid' }])
            logic.actions.filterDashboard()
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

    it('opens adjacent points in the menu while filtering', () => {
        const onFilterDashboard = jest.fn()
        const logic = biDrilldownLogic({ key: 'active', query, onFilterDashboard, dashboardFilterActive: true })
        const unmount = logic.mount()
        try {
            for (const status of ['paid', 'refunded', 'refunded']) {
                logic.actions.setInteraction({ x: 300, y: 250, clickCount: 1 })
                logic.actions.inspect({ status })
                expect(onFilterDashboard).not.toHaveBeenCalled()
                expect(logic.values.record).toEqual({ status })
            }
            expect(onFilterDashboard).not.toHaveBeenCalled()
            logic.actions.setInteraction({ x: 300, y: 250, clickCount: 1 })
            logic.actions.inspect({ count: 8 })
            expect(onFilterDashboard).not.toHaveBeenCalled()
            expect(logic.values.record).toEqual({ count: 8 })
        } finally {
            unmount()
        }
    })

    it.each([{ count: 8 }, { status: 'paid', bi_comparison: 'Previous period' }])(
        'keeps unsupported results available for exploration: %j',
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
                expect(logic.values.record).toEqual(record)
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
