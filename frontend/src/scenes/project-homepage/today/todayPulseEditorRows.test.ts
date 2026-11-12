import type { PulsePinApi } from 'products/today/frontend/generated/api.schemas'

import { IGNORED_TOGGLE, editorNotes, editorRows } from './todayPulseEditorRows'

const row = (key: string): PulsePinApi => ({ key, name: key, dashboard_id: null })

describe('todayPulseEditorRows', () => {
    it.each([
        {
            name: 'a search result pinned while the editor is open',
            pulsePins: ['a', 'x'],
            pinnedThisTime: ['x'],
            expected: [
                ['a', 'x'],
                ['s1', 's2', 'r1'],
            ],
        },
        {
            name: 'that search result after it is unpinned again',
            pulsePins: ['a'],
            pinnedThisTime: ['x'],
            expected: [
                ['a', 'x'],
                ['s1', 's2', 'r1'],
            ],
        },
        {
            name: 'a suggestion pinned while the editor is open',
            pulsePins: ['a', 's2'],
            pinnedThisTime: [],
            expected: [['a'], ['s1', 's2', 'r1', 'x']],
        },
        {
            name: 'a search that matches a recent insight before the server answers',
            search: 'r1',
            pulsePins: ['a'],
            pinnedThisTime: [],
            expected: [['r1']],
        },
        {
            name: 'ignored numbers, listed once under a closed Ignored row',
            pulsePins: ['a'],
            pinnedThisTime: [],
            ignored: ['s2', 'r1'],
            expected: [['a'], ['s1', 'x'], [IGNORED_TOGGLE]],
        },
        {
            name: 'ignored numbers under an open Ignored row',
            pulsePins: ['a'],
            pinnedThisTime: [],
            ignored: ['s2'],
            ignoredOpen: true,
            expected: [['a'], ['s1', 'r1', 'x'], [IGNORED_TOGGLE, 'today-pulse-editor:ignored:s2']],
        },
        {
            name: 'a search while numbers are ignored',
            search: 's',
            pulsePins: ['a'],
            pinnedThisTime: [],
            ignored: ['s2'],
            ignoredOpen: true,
            expected: [['s1']],
        },
        {
            name: 'numbers from other products, which cannot be pinned',
            pulsePins: ['a'],
            pinnedThisTime: [],
            others: ['s1', 'experiment:7', 'evaluation:9', 's2'],
            expected: [['a'], ['s1', 's2', 'r1', 'x']],
        },
    ])(
        'keeps rows in place for $name',
        ({
            search = '',
            pulsePins,
            pinnedThisTime,
            others = ['s1', 's2'],
            ignored = [],
            ignoredOpen = false,
            expected,
        }) => {
            const { groups } = editorRows({
                search,
                pulsePins: pulsePins.map(row),
                pinnedOnOpen: [row('a')],
                othersOnOpen: others.map(row),
                pinnedThisTime: pinnedThisTime.map(row),
                recentInsights: [row('r1'), row('x')],
                searchInsights: [],
                ignored: ignored.map((key) => ({ key, name: key })),
                ignoredOpen,
            })
            expect(groups.map((group) => group.items)).toEqual(expected)
        }
    )

    it.each([
        { loading: true, failed: false, expected: 'Loading your insights…' },
        { loading: false, failed: true, expected: "Couldn't load your insights. Close and open Edit to try again." },
        { loading: false, failed: false, expected: null },
    ])('shows the recent insights request state when nothing is listed', ({ loading, failed, expected }) => {
        expect(editorNotes(false, 0, loading, failed).statusNote).toBe(expected)
    })
})
