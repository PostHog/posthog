import { act, renderHook } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from './traceDrawerLogic'
import { TRACE_DRAWER_OPEN_ROW_CLASS } from './traceDrawerRows'
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

    it('highlights only the selected generation when two rows share a trace', () => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: true })
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
