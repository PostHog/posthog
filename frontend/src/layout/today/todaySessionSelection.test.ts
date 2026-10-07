import {
    TodaySessionSelection,
    bulkArchiveWarning,
    computeBulkPinDirection,
    computeRangeSelection,
    orderedVisibleSessionIds,
    rightClickActsOnSelection,
    toggleSelection,
} from './todaySessionSelection'
import { TodayWorkSectionId } from './todaySpacesLogic'
import { TodayWorkItem } from './todayWorkItems'

const ORDERED = ['t1', 't2', 't3', 't4', 't5']

function item(id: string, kind: TodayWorkItem['kind'] = 'session'): TodayWorkItem {
    return { id, kind } as TodayWorkItem
}

describe('todaySessionSelection', () => {
    it.each<[string, string[], string, boolean]>([
        ['a row inside a selection gets the selection menu', ['t1', 't2'], 't2', true],
        ['a row outside the selection gets its own menu', ['t1', 't2'], 't3', false],
        ['a lone picked row gets its own menu', ['t1'], 't1', false],
    ])('right-click: %s', (_, selected, target, expected) => {
        expect(rightClickActsOnSelection(selected, target)).toBe(expected)
    })

    it.each<[string, string | null, string, string[], TodaySessionSelection]>([
        ['selects a forward range', 't2', 't4', [], { ids: ['t2', 't3', 't4'], anchorId: 't4' }],
        ['selects a backward range', 't4', 't2', [], { ids: ['t2', 't3', 't4'], anchorId: 't2' }],
        ['keeps the rest of the selection', 't3', 't5', ['t1'], { ids: ['t1', 't3', 't4', 't5'], anchorId: 't5' }],
        ['selects only the target with no anchor', null, 't3', ['t1'], { ids: ['t3'], anchorId: 't3' }],
        ['selects only the target when the anchor left the list', 't99', 't3', [], { ids: ['t3'], anchorId: 't3' }],
    ])('Shift-click %s', (_, anchor, target, current, expected) => {
        expect(computeRangeSelection(anchor, target, ORDERED, current)).toEqual(expected)
    })

    it.each<[string, TodaySessionSelection, TodaySessionSelection]>([
        [
            'adds a row and moves the anchor to it',
            { ids: ['t1'], anchorId: 't1' },
            { ids: ['t1', 't3'], anchorId: 't3' },
        ],
        [
            'removes a row and still anchors there',
            { ids: ['t1', 't3'], anchorId: 't1' },
            { ids: ['t1'], anchorId: 't3' },
        ],
    ])('Cmd-click %s', (_, before, after) => {
        expect(toggleSelection(before, 't3')).toEqual(after)
    })

    it.each<[string, TodayWorkSectionId[], string[]]>([
        ['runs Pinned then Recent and skips chats', [], ['p1', 'r1', 'r2']],
        ['skips a collapsed section', ['pinned'], ['r1', 'r2']],
    ])('visible order %s', (_, collapsed, expected) => {
        const recent = [item('r1'), item('chat', 'chat'), item('r2')]
        expect(orderedVisibleSessionIds([item('p1')], recent, collapsed)).toEqual(expected)
    })

    it.each<[string, string[], 'pin' | 'unpin']>([
        ['pins when nothing is pinned', ['t1', 't2'], 'pin'],
        ['pins a mixed selection', ['t1', 'p1'], 'pin'],
        ['unpins when all are pinned', ['p1', 'p2'], 'unpin'],
    ])('bulk pin %s', (_, ids, expected) => {
        expect(computeBulkPinDirection(ids, new Set(['p1', 'p2']))).toEqual(expected)
    })

    it.each([
        [
            3,
            1,
            '1 of these 3 sessions is still running. Archiving it will stop its cloud run and shut down the sandbox. You can unarchive them later.',
        ],
        [
            2,
            2,
            'These 2 sessions are still running. Archiving them will stop their cloud runs and shut down the sandboxes. You can unarchive them later.',
        ],
    ])('names the count when archiving %i sessions with %i running', (count, running, expected) => {
        expect(bulkArchiveWarning(count, running)).toEqual(expected)
    })
})
