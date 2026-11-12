import { renderHook } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

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
})
