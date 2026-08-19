import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabUiStateLogic } from 'lib/logic/tabUiStateLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

jest.mock('~/queries/query')

const TAB_A = 'tab-a'
const TAB_B = 'tab-b'

describe('tabUiStateLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        tabUiStateLogic.mount()
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
})
