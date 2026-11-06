import { renderHook } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { useTraceDrawerRows } from './TraceDrawerRowsHost'
import { TraceListRow } from './traceListRows'

const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN
const ROW: TraceListRow = { traceId: 'a', timestamp: null, stepId: null }

describe('useTraceDrawerRows', () => {
    function setUp(flag: boolean): ReturnType<typeof useTraceDrawerRows> {
        initKeaTests()
        localStorage.clear()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: flag })
        return renderHook(() => useTraceDrawerRows('traces', 'a')).result.current
    }

    it.each([
        ['a row with no trace', true, null],
        ['a list with the drawer disabled', false, ROW],
    ])('adds nothing for %s', (_name, flag, row) => {
        expect(setUp(flag).rowProps(row)).toEqual({})
    })

    it.each([
        ['traces', true],
        ['dataset-items', false],
    ] as const)('marks %s rows as clickable only when the row opens the drawer: %s', (listId, clickable) => {
        initKeaTests()
        localStorage.clear()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: true })
        const { rowProps } = renderHook(() => useTraceDrawerRows(listId, 'a')).result.current

        expect(rowProps(ROW).className?.includes('cursor-pointer')).toBe(clickable)
    })
})
