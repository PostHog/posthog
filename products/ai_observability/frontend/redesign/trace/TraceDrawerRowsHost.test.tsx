import { act, renderHook } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from './traceDrawerLogic'
import { TRACE_DRAWER_OPEN_ROW_CLASS } from './traceDrawerRows'
import { useTraceDrawerRows } from './TraceDrawerRowsHost'
import { TraceListRow } from './traceListRows'

const ROW: TraceListRow = { traceId: 'a', timestamp: null, stepId: null }

describe('useTraceDrawerRows', () => {
    function setUp(listId: 'traces' | 'dataset-items' = 'traces'): ReturnType<typeof useTraceDrawerRows> {
        initKeaTests()
        localStorage.clear()
        return renderHook(() => useTraceDrawerRows(listId, 'a')).result.current
    }

    it('adds nothing for a row with no trace', () => {
        expect(setUp().rowProps(null)).toEqual({})
    })

    it.each([
        ['traces', true],
        ['dataset-items', false],
    ] as const)('marks %s rows as clickable only when the row opens the drawer: %s', (listId, clickable) => {
        expect(setUp(listId).rowProps(ROW).className?.includes('cursor-pointer')).toBe(clickable)
    })

    it('highlights only the selected generation when two rows share a trace', () => {
        initKeaTests()
        router.actions.push(urls.aiObservabilityClusters())
        const { result } = renderHook(() => useTraceDrawerRows('clusters', 'a'))
        const first = { ...ROW, stepId: 'generation-1' }
        const second = { ...ROW, stepId: 'generation-2' }
        const drawer = traceDrawerLogic({ listId: 'clusters' })

        act(() => drawer.actions.openRow(first))
        expect(result.current.rowProps(first).className).toContain(TRACE_DRAWER_OPEN_ROW_CLASS)
        expect(result.current.rowProps(second).className).not.toContain(TRACE_DRAWER_OPEN_ROW_CLASS)
        expect(result.current.rowProps(ROW).className).toContain(TRACE_DRAWER_OPEN_ROW_CLASS)

        act(() => drawer.actions.openRow(second))
        expect(result.current.rowProps(first).className).not.toContain(TRACE_DRAWER_OPEN_ROW_CLASS)
        expect(result.current.rowProps(second).className).toContain(TRACE_DRAWER_OPEN_ROW_CLASS)
    })
})
