import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { getSelectionState, listSelectionLogic, PageItem } from './listSelectionLogic'

/** Helper: create a PageItem[] where all items are editable */
function editable(...ids: number[]): PageItem[] {
    return ids.map((id) => ({ id, isEditable: true }))
}

describe('listSelectionLogic', () => {
    let logic: ReturnType<typeof listSelectionLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = listSelectionLogic({ resource: 'feature_flags' })
        logic.mount()
    })

    describe('getSelectionState (pure function)', () => {
        it('returns both false when editableIds is empty', () => {
            expect(getSelectionState([1, 2, 3], [])).toEqual({ isAllSelected: false, isSomeSelected: false })
        })

        it('returns isAllSelected true and isSomeSelected false when all editable IDs are selected', () => {
            expect(getSelectionState([1, 2, 3], [1, 2, 3])).toEqual({ isAllSelected: true, isSomeSelected: false })
        })

        it('returns isAllSelected true when selectedIds is a superset of editableIds', () => {
            expect(getSelectionState([1, 2, 3, 4, 5], [1, 2, 3])).toEqual({
                isAllSelected: true,
                isSomeSelected: false,
            })
        })

        it('returns isSomeSelected true when only some editable IDs are selected', () => {
            expect(getSelectionState([1], [1, 2, 3])).toEqual({ isAllSelected: false, isSomeSelected: true })
        })

        it('returns both false when no editable IDs are selected', () => {
            expect(getSelectionState([4, 5], [1, 2, 3])).toEqual({ isAllSelected: false, isSomeSelected: false })
        })

        it('returns both false when selectedIds is empty', () => {
            expect(getSelectionState([], [1, 2, 3])).toEqual({ isAllSelected: false, isSomeSelected: false })
        })

        it('returns both false when both arrays are empty', () => {
            expect(getSelectionState([], [])).toEqual({ isAllSelected: false, isSomeSelected: false })
        })
    })

    describe('initial state', () => {
        it('starts with no selected IDs', () => {
            expectLogic(logic).toMatchValues({
                selectedIds: [],
                selectedCount: 0,
                previouslyCheckedIndex: null,
                shiftKeyHeld: false,
            })
        })
    })

    describe('toggleSelection (single click, no shift)', () => {
        it('adds an unselected item to selectedIds', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelection(10, 0, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [10] })
        })

        it('removes a selected item from selectedIds', async () => {
            logic.actions.setSelectedIds([10, 20])

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(10, 0, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [20] })
        })

        it('updates previouslyCheckedIndex to the clicked index', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelection(10, 2, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setPreviouslyCheckedIndex'])
                .toMatchValues({ previouslyCheckedIndex: 2 })
        })

        it('updates previouslyCheckedIndex when deselecting', async () => {
            logic.actions.setSelectedIds([10])

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(10, 1, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setPreviouslyCheckedIndex'])
                .toMatchValues({ previouslyCheckedIndex: 1 })
        })

        it('selecting a second item appends to existing selection', async () => {
            logic.actions.setSelectedIds([10])

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(20, 1, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([10, 20]) })
        })
    })

    describe('toggleSelection with shift-click', () => {
        it('selects a range of IDs when clicking forward from anchor', async () => {
            logic.actions.setPreviouslyCheckedIndex(0)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(30, 2, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([10, 20, 30]) })
        })

        it('selects a range of IDs when clicking backward from anchor', async () => {
            logic.actions.setPreviouslyCheckedIndex(2)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(10, 0, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([10, 20, 30]) })
        })

        it('deselects a range when the clicked item is already selected', async () => {
            logic.actions.setSelectedIds([10, 20, 30])
            logic.actions.setPreviouslyCheckedIndex(0)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(30, 2, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [] })
        })

        it('preserves existing selections outside the range when selecting', async () => {
            logic.actions.setSelectedIds([99])
            logic.actions.setPreviouslyCheckedIndex(0)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(20, 1, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({
                    selectedIds: expect.arrayContaining([99, 10, 20]),
                })
        })

        it('preserves existing selections outside the range when deselecting', async () => {
            logic.actions.setSelectedIds([10, 20, 99])
            logic.actions.setPreviouslyCheckedIndex(0)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(20, 1, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [99] })
        })

        it('selects a single item when anchor equals clicked index', async () => {
            logic.actions.setPreviouslyCheckedIndex(1)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(20, 1, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [20] })
        })

        it('falls back to single toggle when previouslyCheckedIndex is null', async () => {
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(20, 1, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [20] })
        })

        it('updates previouslyCheckedIndex to the clicked index after shift-click', async () => {
            logic.actions.setPreviouslyCheckedIndex(0)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(30, 2, editable(10, 20, 30))
            })
                .toDispatchActions(['toggleSelection', 'setPreviouslyCheckedIndex'])
                .toMatchValues({ previouslyCheckedIndex: 2 })
        })

        it('skips non-editable items in a shift-click range', async () => {
            // Page: [editable:10, non-editable:20, editable:30, editable:40]
            const items: PageItem[] = [
                { id: 10, isEditable: true },
                { id: 20, isEditable: false },
                { id: 30, isEditable: true },
                { id: 40, isEditable: true },
            ]
            logic.actions.setPreviouslyCheckedIndex(0)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(40, 3, items)
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([10, 30, 40]) })

            // Non-editable item 20 must NOT be selected
            expect(logic.values.selectedIds).not.toContain(20)
        })

        it('deselects only editable items in a shift-click range with non-editable items', async () => {
            const items: PageItem[] = [
                { id: 10, isEditable: true },
                { id: 20, isEditable: false },
                { id: 30, isEditable: true },
            ]
            logic.actions.setSelectedIds([10, 30])
            logic.actions.setPreviouslyCheckedIndex(0)
            logic.actions.setShiftKeyHeld(true)

            await expectLogic(logic, () => {
                logic.actions.toggleSelection(30, 2, items)
            })
                .toDispatchActions(['toggleSelection', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [] })
        })
    })

    describe('selectAllOnPage', () => {
        it('selects all editable IDs when none are selected', async () => {
            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage(editable(10, 20, 30))
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([10, 20, 30]) })
        })

        it('selects all editable IDs when only some are selected', async () => {
            logic.actions.setSelectedIds([10])

            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage(editable(10, 20, 30))
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([10, 20, 30]) })
        })

        it('deselects all page IDs when all are already selected', async () => {
            logic.actions.setSelectedIds([10, 20, 30])

            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage(editable(10, 20, 30))
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [] })
        })

        it('preserves selections from other pages when deselecting the current page', async () => {
            logic.actions.setSelectedIds([10, 20, 30, 99, 100])

            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage(editable(10, 20, 30))
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([99, 100]) })
        })

        it('preserves selections from other pages when selecting the current page', async () => {
            logic.actions.setSelectedIds([99, 100])

            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage(editable(10, 20, 30))
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([99, 100, 10, 20, 30]) })
        })

        it('does not add duplicates when re-selecting already selected items', async () => {
            logic.actions.setSelectedIds([10])

            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage(editable(10, 20))
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({
                    selectedIds: expect.arrayContaining([10, 20]),
                    selectedCount: 2,
                })
        })

        it('does nothing when page is empty and nothing is selected', async () => {
            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage([])
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({ selectedIds: [] })
        })

        it('only selects editable items when page has a mix of editable and non-editable', async () => {
            const items: PageItem[] = [
                { id: 10, isEditable: true },
                { id: 20, isEditable: false },
                { id: 30, isEditable: true },
            ]

            await expectLogic(logic, () => {
                logic.actions.selectAllOnPage(items)
            })
                .toDispatchActions(['selectAllOnPage', 'setSelectedIds'])
                .toMatchValues({ selectedIds: expect.arrayContaining([10, 30]) })

            expect(logic.values.selectedIds).not.toContain(20)
        })
    })

    describe('clearSelection', () => {
        it('resets selectedIds to empty', async () => {
            logic.actions.setSelectedIds([1, 2, 3])

            await expectLogic(logic, () => {
                logic.actions.clearSelection()
            })
                .toDispatchActions(['clearSelection'])
                .toMatchValues({ selectedIds: [] })
        })

        it('resets previouslyCheckedIndex to null', async () => {
            logic.actions.setPreviouslyCheckedIndex(5)

            await expectLogic(logic, () => {
                logic.actions.clearSelection()
            })
                .toDispatchActions(['clearSelection'])
                .toMatchValues({ previouslyCheckedIndex: null })
        })

        it('resets both selectedIds and previouslyCheckedIndex together', async () => {
            logic.actions.setSelectedIds([1, 2])
            logic.actions.setPreviouslyCheckedIndex(3)

            await expectLogic(logic, () => {
                logic.actions.clearSelection()
            })
                .toDispatchActions(['clearSelection'])
                .toMatchValues({ selectedIds: [], previouslyCheckedIndex: null })
        })
    })

    describe('selectors', () => {
        it('selectedCount returns the number of selected IDs', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSelectedIds([1, 2, 3])
            })
                .toDispatchActions(['setSelectedIds'])
                .toMatchValues({ selectedCount: 3 })
        })

        it('selectedCount is 0 when nothing is selected', () => {
            expectLogic(logic).toMatchValues({ selectedCount: 0 })
        })

        it('selectedIdsSet returns a Set containing the selected IDs', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSelectedIds([10, 20, 30])
            })
                .toDispatchActions(['setSelectedIds'])
                .toMatchValues({ selectedIdsSet: new Set([10, 20, 30]) })
        })

        it('selectedIdsSet returns an empty Set when nothing is selected', () => {
            expectLogic(logic).toMatchValues({ selectedIdsSet: new Set() })
        })

        it('selectedIdsSet supports membership testing', async () => {
            logic.actions.setSelectedIds([10, 20])
            expect(logic.values.selectedIdsSet.has(10)).toBe(true)
            expect(logic.values.selectedIdsSet.has(30)).toBe(false)
        })
    })
})
