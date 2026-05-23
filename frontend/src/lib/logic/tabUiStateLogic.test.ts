import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    TAB_UI_STATE_STORAGE_KEY,
    TAB_UI_STATE_STORAGE_VERSION,
    TAB_UI_STATE_TTL_MS,
    readPersistedState,
    tabUiStateLogic,
} from 'lib/logic/tabUiStateLogic'

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
        window.localStorage.clear()
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

    describe('savedQueriesByTabAndScene', () => {
        const queryA = setLatestVersionsOnQuery({
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.EventsQuery, select: ['event'] },
        })
        const queryB = setLatestVersionsOnQuery({
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.EventsQuery, select: ['timestamp'] },
        })

        it('persists and reads queries scoped by tabId + sceneKey', () => {
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', queryA)
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'sessions', queryB)

            expect(tabUiStateLogic.values.savedQueryFor(TAB_A, 'events')).toEqual(queryA)
            expect(tabUiStateLogic.values.savedQueryFor(TAB_A, 'sessions')).toEqual(queryB)
        })

        it('isolates saved queries between tabs', () => {
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', queryA)
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_B, 'events', queryB)

            expect(tabUiStateLogic.values.savedQueryFor(TAB_A, 'events')).toEqual(queryA)
            expect(tabUiStateLogic.values.savedQueryFor(TAB_B, 'events')).toEqual(queryB)
        })

        it('returns null for unknown tab/sceneKey', () => {
            expect(tabUiStateLogic.values.savedQueryFor('unknown', 'events')).toBeNull()
            expect(tabUiStateLogic.values.savedQueryFor(undefined, 'events')).toBeNull()
        })

        it('clears the slot when called with null', () => {
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', queryA)
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', null)

            expect(tabUiStateLogic.values.savedQueryFor(TAB_A, 'events')).toBeNull()
        })

        it('null clear of one sceneKey leaves the other intact', () => {
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', queryA)
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'sessions', queryB)
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', null)

            expect(tabUiStateLogic.values.savedQueryFor(TAB_A, 'events')).toBeNull()
            expect(tabUiStateLogic.values.savedQueryFor(TAB_A, 'sessions')).toEqual(queryB)
        })

        it('null clear of last sceneKey drops the tab entry entirely', () => {
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', queryA)
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', null)

            expect(tabUiStateLogic.values.savedQueriesByTabAndScene[TAB_A]).toBeUndefined()
        })

        it('null clear is a no-op for unknown tab/sceneKey', () => {
            const before = tabUiStateLogic.values.savedQueriesByTabAndScene
            tabUiStateLogic.actions.setSavedQueryForTab('never-set', 'events', null)
            expect(tabUiStateLogic.values.savedQueriesByTabAndScene).toBe(before)
        })

        it('clearTabUiState wipes saved queries for that tab', () => {
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_A, 'events', queryA)
            tabUiStateLogic.actions.setSavedQueryForTab(TAB_B, 'events', queryB)

            tabUiStateLogic.actions.clearTabUiState(TAB_A)

            expect(tabUiStateLogic.values.savedQueryFor(TAB_A, 'events')).toBeNull()
            expect(tabUiStateLogic.values.savedQueryFor(TAB_B, 'events')).toEqual(queryB)
        })
    })

    describe('chatDraftsByTab', () => {
        it('persists and reads drafts per tabId', () => {
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'rozepsano')
            expect(tabUiStateLogic.values.chatDraftFor(TAB_A)).toBe('rozepsano')
        })

        it('isolates drafts between tabs', () => {
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'one')
            tabUiStateLogic.actions.setChatDraftForTab(TAB_B, 'two')

            expect(tabUiStateLogic.values.chatDraftFor(TAB_A)).toBe('one')
            expect(tabUiStateLogic.values.chatDraftFor(TAB_B)).toBe('two')
        })

        it('returns empty string for unknown tab', () => {
            expect(tabUiStateLogic.values.chatDraftFor('unknown')).toBe('')
            expect(tabUiStateLogic.values.chatDraftFor(undefined)).toBe('')
        })

        it('drops the slot when set to empty string', () => {
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'rozepsano')
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, '')

            expect(tabUiStateLogic.values.chatDraftsByTab[TAB_A]).toBeUndefined()
        })

        it('clearTabUiState wipes chat drafts for that tab', () => {
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'one')
            tabUiStateLogic.actions.setChatDraftForTab(TAB_B, 'two')

            tabUiStateLogic.actions.clearTabUiState(TAB_A)

            expect(tabUiStateLogic.values.chatDraftFor(TAB_A)).toBe('')
            expect(tabUiStateLogic.values.chatDraftFor(TAB_B)).toBe('two')
        })
    })

    describe('localStorage persistence', () => {
        function readEnvelope(): { version: number; updatedAt: number; state: Record<string, any> } | null {
            const raw = window.localStorage.getItem(TAB_UI_STATE_STORAGE_KEY)
            return raw ? JSON.parse(raw) : null
        }

        it('writes a versioned, timestamped envelope on each mutating action', () => {
            const before = Date.now()
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'rozepsano')
            const after = Date.now()

            const env = readEnvelope()
            expect(env).not.toBeNull()
            expect(env!.version).toBe(TAB_UI_STATE_STORAGE_VERSION)
            expect(env!.updatedAt).toBeGreaterThanOrEqual(before)
            expect(env!.updatedAt).toBeLessThanOrEqual(after)
            expect(env!.state.chatDraftsByTab[TAB_A]).toBe('rozepsano')
        })

        it('refreshes updatedAt on every write', async () => {
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'one')
            const first = readEnvelope()!.updatedAt

            await new Promise((r) => setTimeout(r, 5))
            tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'two')
            const second = readEnvelope()!.updatedAt

            expect(second).toBeGreaterThan(first)
        })

        it('readPersistedState returns empty for missing payload', () => {
            window.localStorage.clear()
            expect(readPersistedState()).toEqual({
                expandedRowsByTabAndVizKey: {},
                savedQueriesByTabAndScene: {},
                chatDraftsByTab: {},
            })
        })

        it('readPersistedState ignores payloads with wrong version', () => {
            window.localStorage.setItem(
                TAB_UI_STATE_STORAGE_KEY,
                JSON.stringify({
                    version: TAB_UI_STATE_STORAGE_VERSION + 1,
                    updatedAt: Date.now(),
                    state: { chatDraftsByTab: { [TAB_A]: 'stale' } },
                })
            )
            expect(readPersistedState().chatDraftsByTab).toEqual({})
        })

        it('readPersistedState ignores payloads older than the TTL', () => {
            window.localStorage.setItem(
                TAB_UI_STATE_STORAGE_KEY,
                JSON.stringify({
                    version: TAB_UI_STATE_STORAGE_VERSION,
                    updatedAt: Date.now() - TAB_UI_STATE_TTL_MS - 1,
                    state: { chatDraftsByTab: { [TAB_A]: 'expired' } },
                })
            )
            expect(readPersistedState().chatDraftsByTab).toEqual({})
        })

        it('readPersistedState accepts fresh payloads within the TTL', () => {
            window.localStorage.setItem(
                TAB_UI_STATE_STORAGE_KEY,
                JSON.stringify({
                    version: TAB_UI_STATE_STORAGE_VERSION,
                    updatedAt: Date.now() - 1000,
                    state: {
                        expandedRowsByTabAndVizKey: { [TAB_A]: { [VIZ_KEY]: [1, 2] } },
                        savedQueriesByTabAndScene: {},
                        chatDraftsByTab: { [TAB_A]: 'fresh' },
                    },
                })
            )
            const restored = readPersistedState()
            expect(restored.chatDraftsByTab[TAB_A]).toBe('fresh')
            expect(restored.expandedRowsByTabAndVizKey[TAB_A][VIZ_KEY]).toEqual([1, 2])
        })

        it('readPersistedState recovers from corrupt JSON', () => {
            window.localStorage.setItem(TAB_UI_STATE_STORAGE_KEY, 'not-json{')
            expect(readPersistedState().chatDraftsByTab).toEqual({})
        })

        it('does not crash when localStorage.setItem throws (quota guard)', () => {
            const original = window.localStorage.setItem.bind(window.localStorage)
            const spy = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
                throw new Error('QuotaExceededError')
            })
            const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
            try {
                expect(() => tabUiStateLogic.actions.setChatDraftForTab(TAB_A, 'x')).not.toThrow()
                expect(tabUiStateLogic.values.chatDraftFor(TAB_A)).toBe('x')
            } finally {
                spy.mockRestore()
                warn.mockRestore()
                window.localStorage.setItem = original
            }
        })
    })
})
