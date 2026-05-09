import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabUiStateLogic } from 'lib/logic/tabUiStateLogic'

import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

jest.mock('~/queries/query')

const VIZ_KEY = 'tab-ui-state-test'
const TAB_A = 'tab-a'
const TAB_B = 'tab-b'

const dataTableQuery: DataTableNode = setLatestVersionsOnQuery({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: ['*'] },
})

describe('tabUiStateLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        tabUiStateLogic.mount()
    })

    it('toggles expanded rows scoped by tabId + vizKey', () => {
        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, VIZ_KEY, 3)
        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, VIZ_KEY, 7)
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, VIZ_KEY)).toEqual([3, 7])

        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, VIZ_KEY, 3)
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, VIZ_KEY)).toEqual([7])
    })

    it('isolates expanded rows between tabs', () => {
        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, VIZ_KEY, 1)
        tabUiStateLogic.actions.toggleExpandedRow(TAB_B, VIZ_KEY, 99)

        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, VIZ_KEY)).toEqual([1])
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_B, VIZ_KEY)).toEqual([99])
    })

    it('isolates expanded rows between vizKeys within the same tab', () => {
        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, 'viz-1', 5)
        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, 'viz-2', 9)

        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, 'viz-1')).toEqual([5])
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, 'viz-2')).toEqual([9])
    })

    it('clears all UI state for a tab', () => {
        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, 'viz-1', 1)
        tabUiStateLogic.actions.toggleExpandedRow(TAB_A, 'viz-2', 2)
        tabUiStateLogic.actions.toggleExpandedRow(TAB_B, 'viz-1', 3)

        tabUiStateLogic.actions.clearTabUiState(TAB_A)

        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, 'viz-1')).toEqual([])
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, 'viz-2')).toEqual([])
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_B, 'viz-1')).toEqual([3])
    })

    it('returns empty array for unknown tab/vizKey', () => {
        expect(tabUiStateLogic.values.expandedRowsFor('unknown-tab', 'unknown-viz')).toEqual([])
        expect(tabUiStateLogic.values.expandedRowsFor(undefined, 'unknown-viz')).toEqual([])
    })

    it('survives dataTableLogic unmount and remount with the same tabId/vizKey', () => {
        // Mount, toggle a row, then unmount — simulating React tab switch.
        let logic = dataTableLogic({
            dataKey: 'dk',
            vizKey: VIZ_KEY,
            tabId: TAB_A,
            query: dataTableQuery,
        })
        logic.mount()
        logic.actions.toggleRowExpanded(4)
        expect(logic.values.expandedRows).toEqual([4])
        logic.unmount()

        // Remount with the same identity — state must come back from tabUiStateLogic.
        logic = dataTableLogic({
            dataKey: 'dk',
            vizKey: VIZ_KEY,
            tabId: TAB_A,
            query: dataTableQuery,
        })
        logic.mount()
        expect(logic.values.expandedRows).toEqual([4])
        logic.unmount()
    })

    it('isolates expanded rows when callers use distinct vizKeys per tab', () => {
        const logicA = dataTableLogic({
            dataKey: 'dk-a',
            vizKey: `viz-${TAB_A}`,
            tabId: TAB_A,
            query: dataTableQuery,
        })
        logicA.mount()
        logicA.actions.toggleRowExpanded(1)

        const logicB = dataTableLogic({
            dataKey: 'dk-b',
            vizKey: `viz-${TAB_B}`,
            tabId: TAB_B,
            query: dataTableQuery,
        })
        logicB.mount()
        expect(logicB.values.expandedRows).toEqual([])
        logicB.actions.toggleRowExpanded(2)

        expect(logicA.values.expandedRows).toEqual([1])
        expect(logicB.values.expandedRows).toEqual([2])

        logicA.unmount()
        logicB.unmount()

        // State survives both unmounts — the global owns it.
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_A, `viz-${TAB_A}`)).toEqual([1])
        expect(tabUiStateLogic.values.expandedRowsFor(TAB_B, `viz-${TAB_B}`)).toEqual([2])
    })
})
