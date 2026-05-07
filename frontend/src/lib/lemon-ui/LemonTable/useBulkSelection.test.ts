import { act, renderHook } from '@testing-library/react'

import { BulkSelectionHandle, BulkSelectionRowGate, useBulkSelection } from './useBulkSelection'

interface Row {
    id: number
    canEdit?: boolean
}

const PAGE: Row[] = [
    { id: 1, canEdit: true },
    { id: 2, canEdit: true },
    { id: 3, canEdit: false },
    { id: 4, canEdit: true },
]

const getKey = (row: Row): number => row.id
const editableGate = (row: Row): BulkSelectionRowGate => (row.canEdit ? true : { disabledReason: 'no permission' })

describe('useBulkSelection', () => {
    it('starts with no selection', () => {
        const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
        expect(result.current.selectedKeys).toEqual([])
        expect(result.current.isAllOnPageSelected).toBe(false)
        expect(result.current.isSomeOnPageSelected).toBe(false)
    })

    it('toggleRow toggles a single row in and out of the selection', () => {
        const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
        act(() => result.current.toggleRow(2, 1))
        expect(result.current.selectedKeys).toEqual([2])
        expect(result.current.isSomeOnPageSelected).toBe(true)
        act(() => result.current.toggleRow(2, 1))
        expect(result.current.selectedKeys).toEqual([])
    })

    it('toggleAllOnPage selects every row when none of the page is selected', () => {
        const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
        act(() => result.current.toggleAllOnPage())
        expect(result.current.selectedKeys.sort()).toEqual([1, 2, 3, 4])
        expect(result.current.isAllOnPageSelected).toBe(true)
    })

    it('toggleAllOnPage skips rows that fail the selectable gate', () => {
        const { result } = renderHook(() =>
            useBulkSelection({ pageRecords: PAGE, getKey, isRowSelectable: editableGate })
        )
        act(() => result.current.toggleAllOnPage())
        expect(result.current.selectedKeys.sort()).toEqual([1, 2, 4])
        expect(result.current.isAllOnPageSelected).toBe(true)
    })

    it('toggleAllOnPage clears the page when everything on it is already selected', () => {
        const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
        act(() => result.current.toggleAllOnPage())
        act(() => result.current.toggleAllOnPage())
        expect(result.current.selectedKeys).toEqual([])
    })

    it('isSomeOnPageSelected is true while a partial subset of the page is selected', () => {
        const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
        act(() => result.current.toggleRow(1, 0))
        expect(result.current.isSomeOnPageSelected).toBe(true)
        expect(result.current.isAllOnPageSelected).toBe(false)
    })

    it('setSelectedKeys deduplicates and replaces the existing selection', () => {
        const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
        act(() => result.current.setSelectedKeys([1, 1, 2, 3]))
        expect(result.current.selectedKeys.sort()).toEqual([1, 2, 3])
    })

    it('clearSelection empties the selection', () => {
        const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
        act(() => result.current.setSelectedKeys([1, 2]))
        act(() => result.current.clearSelection())
        expect(result.current.selectedKeys).toEqual([])
    })

    it('selectedRecords reflects only records currently on the page', () => {
        const { result, rerender } = renderHook(
            ({ pageRecords }: { pageRecords: Row[] }) => useBulkSelection({ pageRecords, getKey }),
            { initialProps: { pageRecords: PAGE } }
        )
        act(() => result.current.setSelectedKeys([1, 999]))
        expect(result.current.context.selectedRecords.map((r) => r.id)).toEqual([1])
        expect(result.current.context.selectedKeys).toEqual([1, 999])
        rerender({ pageRecords: [{ id: 999, canEdit: true }] })
        expect(result.current.context.selectedRecords.map((r) => r.id)).toEqual([999])
    })

    it('exposes an imperative handle when handleRef is provided', () => {
        const handleRef: { current: BulkSelectionHandle | null } = { current: null }
        const { result } = renderHook(() =>
            useBulkSelection<Row>({
                pageRecords: PAGE,
                getKey,
                handleRef,
            })
        )
        expect(handleRef.current).not.toBeNull()
        act(() => handleRef.current!.setSelectedKeys([2, 3]))
        expect([...result.current.selectedKeys].sort()).toEqual([2, 3])
        act(() => handleRef.current!.clearSelection())
        expect(result.current.selectedKeys).toEqual([])
    })

    describe('shift-click range selection', () => {
        it.each([
            {
                scenario: 'forward range from anchor 1 to 3',
                anchorIndex: 1,
                shiftIndex: 3,
                expected: [2, 3, 4],
            },
            {
                scenario: 'backward range from anchor 3 to 1',
                anchorIndex: 3,
                shiftIndex: 1,
                expected: [2, 3, 4],
            },
        ])('selects rows for $scenario', ({ anchorIndex, shiftIndex, expected }) => {
            const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
            const anchorKey = PAGE[anchorIndex].id
            const shiftKey = PAGE[shiftIndex].id

            act(() => result.current.toggleRow(anchorKey, anchorIndex))
            act(() => result.current.toggleRow(shiftKey, shiftIndex, true))

            expect([...result.current.selectedKeys].sort()).toEqual(expected.sort())
        })

        it('skips non-selectable rows in the shift-click range', () => {
            const { result } = renderHook(() =>
                useBulkSelection({ pageRecords: PAGE, getKey, isRowSelectable: editableGate })
            )
            act(() => result.current.toggleRow(1, 0))
            act(() => result.current.toggleRow(4, 3, true))
            // Row at index 2 (id 3) has `canEdit: false` and must be excluded
            expect([...result.current.selectedKeys].sort()).toEqual([1, 2, 4])
        })

        it('deselects only rows inside the shift-click range without disturbing others', () => {
            const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
            act(() => result.current.setSelectedKeys([1, 2, 3, 4]))
            act(() => result.current.toggleRow(1, 0))
            act(() => result.current.toggleRow(3, 2, true))
            expect([...result.current.selectedKeys].sort()).toEqual([4])
        })

        it('falls back to single-row toggle when no previous anchor is set', () => {
            const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
            act(() => result.current.toggleRow(2, 1, true))
            expect(result.current.selectedKeys).toEqual([2])
        })

        it('updates the anchor on every toggle so the next shift-click ranges from the latest click', () => {
            const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
            act(() => result.current.toggleRow(1, 0))
            act(() => result.current.toggleRow(2, 1))
            act(() => result.current.toggleRow(4, 3, true))
            expect([...result.current.selectedKeys].sort()).toEqual([1, 2, 3, 4])
        })

        it('does not extend a range when shift is not held', () => {
            const { result } = renderHook(() => useBulkSelection({ pageRecords: PAGE, getKey }))
            act(() => result.current.toggleRow(1, 0))
            act(() => result.current.toggleRow(4, 3))
            expect([...result.current.selectedKeys].sort()).toEqual([1, 4])
        })
    })
})
